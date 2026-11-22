// blehid.c — minimal Bluetooth LE HID mouse for the relocated Glorious Model O Pro Wireless firmware.
//
// This module is only a transport. Everything that makes the mouse a mouse (sensor, buttons, remap engine, DPI, polling
// timer, report builder, battery measurement, LED effects, idle sleep) is the vendor ("stock") firmware, unchanged.
// tools/mk_ble.py hooks the stock code at a few points and calls the entry points in ENTRY[] at the start of this blob.
//
// Behaviour
//   * Two modes, kept in the config record (page 0xF6000) and toggled with DPI + Back + Forward held 3 s (then reboot):
//       RF  = the stock firmware as shipped, SoftDevice off: 2.4 GHz dongle, and USB when a data cable is enumerated.
//       BLE = SoftDevice on; mouse reports go over BLE only, a cable only charges (REPORT_T in mk_ble.py).
//   * One host. Pairing is accepted only while no host is bonded. Left + Right + DPI held 3 s forgets the host, moves the
//     mouse to a new BLE address (the old host cannot reconnect with its stale key) and reboots ready to pair.
//   * The mouse asks the host for a 7.5 ms connection interval (the BLE minimum) after connecting and again once the link
//     is encrypted.
//   * No power saving of its own: advertising every 50 ms without timeout, no slave latency. The stock 7-minute idle sleep
//     still happens (mk_ble.py only makes it SoftDevice-safe).
//   * DPI + Left + Back held 3 s (both modes) reboots into the Nordic DFU bootloader (fw/bootloader) for an update over BLE.
//
// Flash records: the config record (0xF6000) and the bond record (0xF7000) sit in the bootloader's application data area
// (0xF5000-0xF7FFF, NRF_DFU_APP_DATA_AREA_SIZE = 3 pages), which a DFU update never erases. Above it the bootloader owns
// 0xF8000-0xFFFFF (code, MBR parameter page 0xFE000, settings page 0xFF000) and write-protects it while the app runs.
#include <stdint.h>
#include <stddef.h>
#include "ble.h"
#include "ble_gap.h"
#include "ble_gatts.h"
#include "ble_hci.h"
#include "nrf_soc.h"
#include "nrf_error.h"

#define NAME "Model O PRO Wireless"
#define APPEARANCE_MOUSE 0x03C2
#define LOG ((volatile uint32_t *)0x2003F100)   // [0] magic [1] init result (0x1000 = ok) [2] BLE event count
                                                // [3..18] last 16 event ids [19] last flash write (0 ok, 8 verify failed, 9 error)
#define RTC1_COUNTER (*(volatile uint32_t *)0x40011504)   // stock app timer: 32768 Hz, free running, 24 bit
#define SD_FLAG (*(volatile uint8_t *)0x20003830)         // stock nrf_sdh "SoftDevice enabled" flag: 1 = BLE mode
#define GPIO_P0_IN (*(volatile uint32_t *)0x50000510)
#define GPIO_P1_IN (*(volatile uint32_t *)0x50000810)
// Buttons (inputs are active low): BACK P0.9, FORWARD P0.10, DPI P1.0, RIGHT P1.13, LEFT P1.15
#define MODE_CHORD_P0 ((1u << 9) | (1u << 10))            // mode chord: BACK + FORWARD + DPI
#define MODE_CHORD_P1 (1u << 0)
#define PAIR_CHORD_P1 ((1u << 15) | (1u << 13) | (1u << 0)) // pair chord: LEFT + RIGHT + DPI
#define DFU_CHORD_P0 (1u << 9)                            // DFU chord: DPI + LEFT + BACK
#define DFU_CHORD_P1 ((1u << 15) | (1u << 0))
#define CHORD_TICKS (3u * 32768u)                         // 3 s
#define POWER_GPREGRET (*(volatile uint32_t *)0x4000051C)
#define BOOTLOADER_DFU_START 0xB1                         // GPREGRET value that makes the Nordic bootloader stay in DFU mode

// ---- libc bits the compiler may call (freestanding build)
void *memset(void *d, int c, size_t n) { uint8_t *p = d; while (n--) *p++ = (uint8_t)c; return d; }
void *memcpy(void *d, const void *s, size_t n) { uint8_t *p = d; const uint8_t *q = s; while (n--) *p++ = *q++; return d; }
int memcmp(const void *a, const void *b, size_t n) { const uint8_t *p = a, *q = b; while (n--) { if (*p != *q) return *p - *q; p++; q++; } return 0; }

// HID report map: Report ID 1, 8 buttons, X/Y int16, wheel int8, AC pan int8 (7 bytes after the ID)
static const uint8_t report_map_rom[] = {
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x01, 0x09, 0x01, 0xA1, 0x00,                          // Mouse, ID 1, Pointer
    0x05, 0x09, 0x19, 0x01, 0x29, 0x08, 0x15, 0x00, 0x25, 0x01, 0x95, 0x08, 0x75, 0x01, 0x81, 0x02,  // 8 buttons
    0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x16, 0x01, 0x80, 0x26, 0xFF, 0x7F, 0x75, 0x10, 0x95, 0x02, 0x81, 0x06,  // X, Y
    0x09, 0x38, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06,                          // wheel
    0x05, 0x0C, 0x0A, 0x38, 0x02, 0x95, 0x01, 0x81, 0x06,                                            // AC pan
    0xC0, 0xC0};

typedef struct {
    uint16_t conn;                 // BLE_CONN_HANDLE_INVALID while no host is connected
    uint16_t interval;             // current connection interval (1.25 ms units)
    uint8_t adv_handle, notify_on, bonded, reconn;
    ble_gatts_char_handles_t h_rep, h_map, h_info, h_ctrl, h_proto, h_bat;
    uint16_t svc_hid, svc_bas, svc_dis;
    uint8_t map[sizeof(report_map_rom)];
    uint8_t proto, bat, rep[7], info[4], ctrl, rep_ref[2], pnp[7];
    ble_gap_enc_key_t own_enc, peer_enc;
    ble_gap_id_key_t peer_id;
    ble_gap_sec_keyset_t keyset;
    ble_gap_adv_data_t adv;
    uint8_t adv_buf[31], rsp_buf[31];
    ble_gap_adv_params_t advp;
    uint32_t evt_buf[64];          // 256 B, word aligned, for sd_ble_evt_get
    uint16_t sa_len;
    uint8_t sa[88];                // GATT system attributes of the bonded host (its CCCD state)
    uint8_t mode_on, pair_on, dfu_on;   // chord state
    uint32_t mode_t0, pair_t0, dfu_t0;
    uint8_t led_state, led_color, led_blinks;
    uint16_t led_orig[3];
    uint32_t led_t0;
    uint8_t dirty, reset_after_flash, fl2_n;   // flash writer: bond record pending / reboot when done / chained request
    uint32_t fl2_addr, fl2_buf[4];
    struct { uint8_t state, tries; uint32_t addr, words; uint32_t buf[32]; } fl;
} state_t;

static state_t S;   // lives in the blob's own RAM (0x2000B400, see link.ld); nobody zeroes it, the init functions do

static uint32_t send_report(const uint8_t *rep);
static void wait_ms(uint32_t ms) { uint32_t t0 = RTC1_COUNTER; while (((RTC1_COUNTER - t0) & 0xFFFFFF) < ms * 33) {} }
static void sys_reset(void) { __asm volatile("dsb"); *(volatile uint32_t *)0xE000ED0C = 0x05FA0004; for (;;) {} }
// Leave the host cleanly before a reboot: an all-zero report releases every button on the host (Windows keeps the last
// HID state of a device that just vanishes, and the chords hold Back/Forward/Left/Right), then terminate the link.
static void leave_link(void) {
    static const uint8_t none[7] = {0};
    if (S.conn == BLE_CONN_HANDLE_INVALID) return;
    send_report(none);
    wait_ms(20);
    sd_ble_gap_disconnect(S.conn, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
    wait_ms(30);
}

// ---- LED feedback
// STOCK: the stock LED engine writes the status LED's duty values (R, G, B as u16, bit 15 = PWM polarity) into the PWM0
//        sequence buffer at 0x20003270 and keeps PWM0 running; the PWM0 interrupt drives the engine for both LEDs.
// MOD:   for a blink pattern, save the three stock values, overwrite them, and put the saved values back at the end.
//        PWM0 itself, its interrupt and the DPI LED (PWM1) are never touched.
// Colour bits: 1 = red, 2 = green, 4 = blue (5 = purple).
#define LED_SEQ ((volatile uint16_t *)0x20003270)
static void led_start(uint8_t color, uint8_t blinks) { S.led_color = color; S.led_blinks = blinks; S.led_state = 1; }
static void led_tick(void) {
    if (!S.led_state) return;
    uint32_t now = RTC1_COUNTER;
    if (S.led_state == 1) {
        for (int i = 0; i < 3; i++) S.led_orig[i] = LED_SEQ[i];
        S.led_t0 = now; S.led_state = 2;
    }
    uint32_t ms = ((now - S.led_t0) & 0xFFFFFF) >> 5;
    if (ms >= (uint32_t)S.led_blinks * 500) {
        for (int i = 0; i < 3; i++) LED_SEQ[i] = S.led_orig[i];
        S.led_state = 0;
        return;
    }
    int on = (ms % 500) < 300;   // 300 ms on, 200 ms off
    for (int i = 0; i < 3; i++) LED_SEQ[i] = (on && ((S.led_color >> i) & 1)) ? 0x80C0 : 0x8000;
}

// ---- flash writer (BLE mode). With the SoftDevice on, the NVMC belongs to it: erase/write go through sd_flash_*, which
// run asynchronously; one step per main-loop pass, then a read-back check.
static void flash_request(uint32_t addr, const uint32_t *words, uint32_t n) {
    memcpy(S.fl.buf, words, n * 4);
    S.fl.addr = addr; S.fl.words = n; S.fl.tries = 0; S.fl.state = 1;
}
static void bond_flush(void);
static void flash_step(void) {
    uint32_t r;
    if ((S.fl.state == 0 || S.fl.state >= 8) && S.dirty) { S.dirty = 0; bond_flush(); }
    switch (S.fl.state) {
    case 1:   // erase the page
        r = sd_flash_page_erase(S.fl.addr / 4096);
        if (r == NRF_SUCCESS) S.fl.state = 2; else if (r != NRF_ERROR_BUSY) { LOG[19] = 9; S.fl.state = 9; }
        break;
    case 2:   // write (BUSY until the erase has finished)
        r = sd_flash_write((uint32_t *)S.fl.addr, S.fl.buf, S.fl.words);
        if (r == NRF_SUCCESS) S.fl.state = 3; else if (r != NRF_ERROR_BUSY) { LOG[19] = 9; S.fl.state = 9; }
        break;
    case 3:   // read back after a few passes
        if (++S.fl.tries <= 30) break;
        S.fl.state = memcmp((void *)S.fl.addr, S.fl.buf, S.fl.words * 4) == 0 ? 0 : 8;
        LOG[19] = S.fl.state;
        if (S.fl.state == 0 && S.fl2_n) {   // chained second request (re-pair: config record first, then the bond erase)
            uint8_t n = S.fl2_n; S.fl2_n = 0;
            flash_request(S.fl2_addr, S.fl2_buf, n);
            break;
        }
        if (S.fl.state == 0 && S.reset_after_flash) { leave_link(); sys_reset(); }
        S.reset_after_flash = 0;
        break;
    default:
        break;
    }
}

// ---- bond record: page 0xF7000, 32 words
// [0] magic  [1] checksum of words 2..31  [2..8] our encryption key (LTK, EDIV, RAND, 28 B)
// [9] length of the system attributes (low 16 bits)  [10..31] system attributes = the host's CCCD state, so reports
// flow right after a reconnect without the host subscribing again.
#define BOND_ADDR 0xF7000u
#define BOND_MAGIC 0xB0DD0001u
static uint32_t rec_sum(const uint32_t *w, int n) { uint32_t a = 0x5A5A1234; while (n--) a = (a << 1 | a >> 31) ^ *w++; return a; }
static void bond_load(void) {
    const uint32_t *w = (const uint32_t *)BOND_ADDR;
    if (w[0] != BOND_MAGIC || w[1] != rec_sum(w + 2, 30)) return;
    memcpy(&S.own_enc, w + 2, sizeof S.own_enc);
    S.sa_len = (uint16_t)w[9];
    if (S.sa_len > sizeof S.sa) S.sa_len = 0;
    memcpy(S.sa, w + 10, sizeof S.sa);
    S.bonded = 1;
}
static void bond_flush(void) {
    uint32_t b[32];
    memset(b, 0, sizeof b);
    memcpy(b + 2, &S.own_enc, sizeof S.own_enc);
    b[9] = S.sa_len;
    memcpy(b + 10, S.sa, sizeof S.sa);
    b[0] = BOND_MAGIC;
    b[1] = rec_sum(b + 2, 30);
    flash_request(BOND_ADDR, b, 32);
}
static void bond_save(void) { S.dirty = 1; }   // written by flash_step() as soon as the writer is idle
// copy the host's CCCD state out of the SoftDevice and keep it with the bond
static void sa_capture(uint16_t conn) {
    uint16_t len = sizeof S.sa;
    if (sd_ble_gatts_sys_attr_get(conn, S.sa, &len, BLE_GATTS_SYS_ATTR_FLAG_SYS_SRVCS | BLE_GATTS_SYS_ATTR_FLAG_USR_SRVCS) == NRF_SUCCESS) {
        S.sa_len = len;
        if (S.bonded) bond_save();
    }
}

// ---- config record: page 0xF6000, 4 words: [0] magic [1] mode [2] ~mode [3] pairing generation
// Read by the boot stub in mk_ble.py (mode) and by blehid_init (generation -> BLE address).
#define CFG_ADDR 0xF6000u
#define CFG_MAGIC 0xC0DE0001u
#define MODE_BLE 1
#define MODE_RF 2
static int cfg_valid(const uint32_t *w) { return w[0] == CFG_MAGIC && (w[1] ^ w[2]) == 0xFFFFFFFFu; }
static uint32_t cfg_mode(void) {
    const uint32_t *w = (const uint32_t *)CFG_ADDR;
    return cfg_valid(w) && w[1] == MODE_RF ? MODE_RF : MODE_BLE;   // no record: BLE
}
static uint32_t cfg_gen(void) {
    const uint32_t *w = (const uint32_t *)CFG_ADDR;
    return cfg_valid(w) && w[3] != 0xFFFFFFFFu ? w[3] : 0;
}
// RF mode only (SoftDevice off): the NVMC is ours, write the page directly
#define NVMC_READY (*(volatile uint32_t *)0x4001E400)
#define NVMC_CONFIG (*(volatile uint32_t *)0x4001E504)
#define NVMC_ERASEPAGE (*(volatile uint32_t *)0x4001E508)
static void nvmc_store(uint32_t addr, const uint32_t *w, int n) {
    NVMC_CONFIG = 2; NVMC_ERASEPAGE = addr; while (!NVMC_READY) {}
    NVMC_CONFIG = 1;
    for (int i = 0; i < n; i++) { *(volatile uint32_t *)(addr + 4 * i) = w[i]; while (!NVMC_READY) {} }
    NVMC_CONFIG = 0; while (!NVMC_READY) {}
}

// ---- chords
// Mode chord (both modes): store the other mode and reboot; the boot stub picks the mode.
static void mode_switch(void) {
    uint32_t nxt = cfg_mode() == MODE_BLE ? MODE_RF : MODE_BLE;
    uint32_t rec[4] = {CFG_MAGIC, nxt, ~nxt, cfg_gen()};
    if (SD_FLAG) { S.reset_after_flash = 1; flash_request(CFG_ADDR, rec, 4); }   // flash_step() reboots after leaving the host
    else { nvmc_store(CFG_ADDR, rec, 4); sys_reset(); }
}
// Pair chord (BLE mode): pairing generation + 1 (= new BLE address), erase the bond, reboot. The mouse then advertises
// unbonded from the new address and accepts the next host that pairs.
static void pair_reset(void) {
    uint32_t m = cfg_mode();
    uint32_t cfg[4] = {CFG_MAGIC, m, ~m, cfg_gen() + 1};
    static const uint32_t none[4] = {0, 0, 0, 0};
    memcpy(S.fl2_buf, none, sizeof none); S.fl2_addr = BOND_ADDR; S.fl2_n = 4;
    S.reset_after_flash = 1;
    flash_request(CFG_ADDR, cfg, 4);
}
// DFU chord (both modes): mark GPREGRET = 0xB1 and reboot. The Nordic bootloader (fw/bootloader) sees the mark at boot,
// clears it and stays in DFU mode, advertising for an update. Without the bootloader the mark is ignored (the stock code
// never reads GPREGRET) and the mouse simply reboots. With the SoftDevice on, POWER belongs to it: use its API.
static void dfu_reboot(void) {
    if (SD_FLAG) {
        sd_power_gpregret_clr(0, 0xFF);
        sd_power_gpregret_set(0, BOOTLOADER_DFU_START);
        leave_link();
    } else {
        POWER_GPREGRET = BOOTLOADER_DFU_START;
    }
    sys_reset();
}
// 1 when all buttons of the masks are held for CHORD_TICKS (fires once per hold)
static int chord_held(uint32_t p0, uint32_t p1, uint8_t *on, uint32_t *t0) {
    int down = (~GPIO_P0_IN & p0) == p0 && (~GPIO_P1_IN & p1) == p1;
    uint32_t now = RTC1_COUNTER;
    if (!down) { *on = 0; return 0; }
    if (!*on) { *on = 1; *t0 = now; return 0; }
    if (*on == 1 && ((now - *t0) & 0xFFFFFF) > CHORD_TICKS) { *on = 2; return 1; }
    return 0;
}
static void chords_poll(void) {
    if (S.fl.state >= 1 && S.fl.state <= 3) return;   // a record write (and maybe a reboot) is already under way
    if (chord_held(MODE_CHORD_P0, MODE_CHORD_P1, &S.mode_on, &S.mode_t0)) { mode_switch(); return; }
    if (SD_FLAG && chord_held(0, PAIR_CHORD_P1, &S.pair_on, &S.pair_t0)) { led_start(5, 3); pair_reset(); return; }
    if (chord_held(DFU_CHORD_P0, DFU_CHORD_P1, &S.dfu_on, &S.dfu_t0)) dfu_reboot();
}

static void logev(uint32_t id) { uint32_t n = LOG[2]++; LOG[3 + (n & 15)] = id; }

// ---- GATT helpers
static void sec_mode(ble_gap_conn_sec_mode_t *m, int enc) {
    if (enc) BLE_GAP_CONN_SEC_MODE_SET_ENC_NO_MITM(m); else BLE_GAP_CONN_SEC_MODE_SET_OPEN(m);
}
// props: 1 read, 2 write without response, 4 write, 8 notify
static uint32_t add_char(uint16_t svc, uint16_t uuid16, int props, int enc, uint8_t *val, uint16_t len, ble_gatts_char_handles_t *h) {
    ble_uuid_t uuid = {uuid16, BLE_UUID_TYPE_BLE};
    ble_gatts_char_md_t cmd;
    ble_gatts_attr_md_t amd, cccd;
    ble_gatts_attr_t attr;
    memset(&cmd, 0, sizeof cmd); memset(&amd, 0, sizeof amd); memset(&cccd, 0, sizeof cccd); memset(&attr, 0, sizeof attr);
    cmd.char_props.read = (props & 1) != 0;
    cmd.char_props.write_wo_resp = (props & 2) != 0;
    cmd.char_props.write = (props & 4) != 0;
    cmd.char_props.notify = (props & 8) != 0;
    sec_mode(&amd.read_perm, enc);
    sec_mode(&amd.write_perm, enc);
    amd.vloc = BLE_GATTS_VLOC_USER;   // the value lives in S, which keeps the SoftDevice attribute table small
    attr.p_uuid = &uuid; attr.p_attr_md = &amd; attr.init_len = len; attr.max_len = len; attr.p_value = val;
    if (props & 8) {
        BLE_GAP_CONN_SEC_MODE_SET_OPEN(&cccd.read_perm);
        sec_mode(&cccd.write_perm, enc);
        cccd.vloc = BLE_GATTS_VLOC_STACK;
        cmd.p_cccd_md = &cccd;
    }
    return sd_ble_gatts_characteristic_add(svc, &cmd, &attr, h);
}
static uint32_t add_report_ref(uint16_t char_handle, uint8_t *val) {   // Report Reference descriptor (0x2908)
    ble_uuid_t uuid = {0x2908, BLE_UUID_TYPE_BLE};
    ble_gatts_attr_md_t amd;
    ble_gatts_attr_t attr;
    uint16_t h;
    memset(&amd, 0, sizeof amd); memset(&attr, 0, sizeof attr);
    sec_mode(&amd.read_perm, 1);
    BLE_GAP_CONN_SEC_MODE_SET_NO_ACCESS(&amd.write_perm);
    amd.vloc = BLE_GATTS_VLOC_USER;
    attr.p_uuid = &uuid; attr.p_attr_md = &amd; attr.init_len = 2; attr.max_len = 2; attr.p_value = val;
    return sd_ble_gatts_descriptor_add(char_handle, &attr, &h);
}
static uint32_t add_service(uint16_t uuid16, uint16_t *h) {
    ble_uuid_t uuid = {uuid16, BLE_UUID_TYPE_BLE};
    return sd_ble_gatts_service_add(BLE_GATTS_SRVC_TYPE_PRIMARY, &uuid, h);
}

// ---- RF mode: no SoftDevice, only the mode chord and the boot blink. Called by the boot stub before the stock init.
uint32_t blehid_init_nosd(void) {
    memset(&S, 0, sizeof S);
    S.conn = BLE_CONN_HANDLE_INVALID;
    LOG[0] = 0xB1E0A002;
    led_start(2, 2);   // RF mode: 2 green blinks
    return 0;
}

// ---- BLE mode: called by the boot stub after sd_ble_enable. Returns 0, or the first failing SoftDevice error
// (the failing step is in LOG[1] as 0x100 | step).
#define TRY(step, call) do { uint32_t e_ = (call); if (e_) { LOG[1] = 0x100 | (step); return e_; } } while (0)
uint32_t blehid_init(void) {
    memset(&S, 0, sizeof S);
    for (int i = 0; i < 20; i++) LOG[i] = 0;
    LOG[0] = 0xB1E0A001;
    S.conn = BLE_CONN_HANDLE_INVALID;
    bond_load();
    led_start(S.bonded ? 4 : 5, 2);   // BLE mode: 2 blue blinks with a bonded host, 2 purple blinks when ready to pair
    memcpy(S.map, report_map_rom, sizeof S.map);
    S.proto = 1;                                                           // Report protocol
    S.info[0] = 0x11; S.info[1] = 0x01; S.info[2] = 0; S.info[3] = 0x02;   // HID 1.11, country 0, normally connectable
    S.rep_ref[0] = 1; S.rep_ref[1] = 1;                                    // Report ID 1, Input
    uint8_t v = *(volatile uint8_t *)0x20003076;                           // stock battery percentage
    S.bat = v && v <= 100 ? v : 100;

    // GAP: name, appearance, preferred connection parameters (7.5 ms, no latency, 4 s supervision timeout)
    ble_gap_conn_sec_mode_t open;
    BLE_GAP_CONN_SEC_MODE_SET_OPEN(&open);
    TRY(1, sd_ble_gap_device_name_set(&open, (const uint8_t *)NAME, sizeof NAME - 1));
    TRY(2, sd_ble_gap_appearance_set(APPEARANCE_MOUSE));
    ble_gap_conn_params_t cp = {6, 6, 0, 400};
    TRY(3, sd_ble_gap_ppcp_set(&cp));

    // Device Information: PnP ID (USB VID 0x258A, PID 0x2015 = the stock USB identity)
    static const uint8_t pnp_rom[7] = {0x02, 0x8A, 0x25, 0x15, 0x20, 0x00, 0x01};
    memcpy(S.pnp, pnp_rom, sizeof S.pnp);
    ble_gatts_char_handles_t h_pnp;
    TRY(4, add_service(0x180A, &S.svc_dis));
    TRY(5, add_char(S.svc_dis, 0x2A50, 1, 0, S.pnp, 7, &h_pnp));
    // Battery: level (read + notify); HID over GATT requires this service
    TRY(6, add_service(0x180F, &S.svc_bas));
    TRY(7, add_char(S.svc_bas, 0x2A19, 1 | 8, 0, &S.bat, 1, &S.h_bat));
    // HID: information, report map, control point, protocol mode, input report (+ report reference); all need encryption
    TRY(8, add_service(0x1812, &S.svc_hid));
    TRY(9, add_char(S.svc_hid, 0x2A4A, 1, 1, S.info, 4, &S.h_info));
    TRY(10, add_char(S.svc_hid, 0x2A4B, 1, 1, S.map, sizeof S.map, &S.h_map));
    TRY(11, add_char(S.svc_hid, 0x2A4C, 2, 1, &S.ctrl, 1, &S.h_ctrl));
    TRY(12, add_char(S.svc_hid, 0x2A4E, 1 | 2, 1, &S.proto, 1, &S.h_proto));
    TRY(13, add_char(S.svc_hid, 0x2A4D, 1 | 8, 1, S.rep, 7, &S.h_rep));
    TRY(14, add_report_ref(S.h_rep.value_handle, S.rep_ref));

    // Address: generation 0 = the chip's factory address; after each re-pair a new static random address derived from it
    uint32_t gen = cfg_gen();
    if (gen) {
        uint32_t lo = *(volatile uint32_t *)0x100000A4 ^ (gen * 0x9E3779B1u), hi = *(volatile uint32_t *)0x100000A8;   // FICR DEVICEADDR
        ble_gap_addr_t a;
        memset(&a, 0, sizeof a);
        a.addr_type = BLE_GAP_ADDR_TYPE_RANDOM_STATIC;
        a.addr[0] = (uint8_t)lo; a.addr[1] = (uint8_t)(lo >> 8); a.addr[2] = (uint8_t)(lo >> 16); a.addr[3] = (uint8_t)(lo >> 24);
        a.addr[4] = (uint8_t)hi; a.addr[5] = (uint8_t)((hi >> 8) | 0xC0);   // top two bits 11 = static random
        TRY(15, sd_ble_gap_addr_set(&a));
    }

    // Advertising: flags, appearance, HID service UUID; the name goes in the scan response. Every 50 ms, no timeout.
    uint8_t *a = S.adv_buf, n = 0, m = 0;
    a[n++] = 2; a[n++] = 0x01; a[n++] = 0x06;                                             // LE general discoverable
    a[n++] = 3; a[n++] = 0x19; a[n++] = APPEARANCE_MOUSE & 0xFF; a[n++] = APPEARANCE_MOUSE >> 8;
    a[n++] = 3; a[n++] = 0x03; a[n++] = 0x12; a[n++] = 0x18;                              // 16-bit UUID 0x1812
    S.rsp_buf[m++] = sizeof NAME; S.rsp_buf[m++] = 0x09;
    for (size_t i = 0; i < sizeof NAME - 1; i++) S.rsp_buf[m++] = NAME[i];
    S.adv.adv_data.p_data = S.adv_buf; S.adv.adv_data.len = n;
    S.adv.scan_rsp_data.p_data = S.rsp_buf; S.adv.scan_rsp_data.len = m;
    S.advp.properties.type = BLE_GAP_ADV_TYPE_CONNECTABLE_SCANNABLE_UNDIRECTED;
    S.advp.interval = 80;   // 80 x 0.625 ms = 50 ms
    S.advp.duration = 0;    // until a host connects
    S.advp.primary_phy = BLE_GAP_PHY_1MBPS;
    S.adv_handle = BLE_GAP_ADV_SET_HANDLE_NOT_SET;
    TRY(16, sd_ble_gap_adv_set_configure(&S.adv_handle, &S.adv, &S.advp));
    TRY(17, sd_ble_gap_adv_start(S.adv_handle, BLE_CONN_CFG_TAG_DEFAULT));
    LOG[1] = 0x1000;
    return 0;
}

// LE legacy pairing, Just Works, bonding. We hand out our LTK; the host gives us its LTK and identity.
static const ble_gap_sec_params_t secp = {
    .bond = 1, .mitm = 0, .lesc = 0, .keypress = 0, .io_caps = BLE_GAP_IO_CAPS_NONE, .oob = 0,
    .min_key_size = 7, .max_key_size = 16,
    .kdist_own = {.enc = 1, .id = 0, .sign = 0, .link = 0},
    .kdist_peer = {.enc = 1, .id = 1, .sign = 0, .link = 0}};

// Ask for 7.5 ms (6 x 1.25 ms), no slave latency, 4 s supervision timeout. Hosts often ignore the preferred parameters
// (PPCP), so the mouse requests them explicitly; the host may still choose something else.
static void request_7ms5(uint16_t ch) {
    ble_gap_conn_params_t p = {6, 6, 0, 400};
    sd_ble_gap_conn_param_update(ch, &p);
}

static void on_evt(const ble_evt_t *ev) {
    uint16_t id = ev->header.evt_id;
    uint16_t ch = ev->evt.gap_evt.conn_handle;
    logev(id);
    switch (id) {
    case BLE_GAP_EVT_CONNECTED:
        S.conn = ch;
        S.notify_on = 0;
        S.interval = ev->evt.gap_evt.params.connected.conn_params.max_conn_interval;
        led_start(4, 1);   // one blue blink
        request_7ms5(ch);
        break;
    case BLE_GAP_EVT_DISCONNECTED:
        S.conn = BLE_CONN_HANDLE_INVALID;
        S.notify_on = 0;
        S.reconn = 0;
        sd_ble_gap_adv_start(S.adv_handle, BLE_CONN_CFG_TAG_DEFAULT);   // advertising stopped when the host connected
        break;
    case BLE_GAP_EVT_CONN_PARAM_UPDATE:
        S.interval = ev->evt.gap_evt.params.conn_param_update.conn_params.max_conn_interval;
        break;
    case BLE_GAP_EVT_SEC_PARAMS_REQUEST:   // the host wants to pair
        if (S.bonded) {   // one host only: a new one has to wait for the pair chord
            sd_ble_gap_sec_params_reply(ch, BLE_GAP_SEC_STATUS_PAIRING_NOT_SUPP, NULL, NULL);
            break;
        }
        memset(&S.keyset, 0, sizeof S.keyset);
        S.keyset.keys_own.p_enc_key = &S.own_enc;
        S.keyset.keys_peer.p_enc_key = &S.peer_enc;
        S.keyset.keys_peer.p_id_key = &S.peer_id;
        sd_ble_gap_sec_params_reply(ch, BLE_GAP_SEC_STATUS_SUCCESS, &secp, &S.keyset);
        break;
    case BLE_GAP_EVT_AUTH_STATUS:   // pairing finished
        if (ev->evt.gap_evt.params.auth_status.auth_status == BLE_GAP_SEC_STATUS_SUCCESS) { S.bonded = 1; bond_save(); }
        break;
    case BLE_GAP_EVT_SEC_INFO_REQUEST: {   // the host wants to encrypt with a key it has: answer only for our bonded host
        const ble_gap_evt_sec_info_request_t *r = &ev->evt.gap_evt.params.sec_info_request;
        if (S.bonded && r->enc_info && r->master_id.ediv == S.own_enc.master_id.ediv &&
            memcmp(r->master_id.rand, S.own_enc.master_id.rand, 8) == 0) {
            S.reconn = 1;
            sd_ble_gap_sec_info_reply(ch, &S.own_enc.enc_info, NULL, NULL);
        } else {
            sd_ble_gap_sec_info_reply(ch, NULL, NULL, NULL);
        }
        break;
    }
    case BLE_GAP_EVT_CONN_SEC_UPDATE:   // link encrypted
        if (S.reconn && S.sa_len) {      // our bonded host is back: restore its CCCD state, reports flow without resubscribing
            sd_ble_gatts_sys_attr_set(ch, S.sa, S.sa_len, BLE_GATTS_SYS_ATTR_FLAG_SYS_SRVCS | BLE_GATTS_SYS_ATTR_FLAG_USR_SRVCS);
            S.notify_on = 1;
        }
        S.reconn = 0;
        if (S.interval != 6) request_7ms5(ch);   // some hosts accept the request only once the link is encrypted
        break;
    case BLE_GATTS_EVT_SYS_ATTR_MISSING:
        if (S.bonded && S.sa_len)
            sd_ble_gatts_sys_attr_set(ch, S.sa, S.sa_len, BLE_GATTS_SYS_ATTR_FLAG_SYS_SRVCS | BLE_GATTS_SYS_ATTR_FLAG_USR_SRVCS);
        else
            sd_ble_gatts_sys_attr_set(ch, NULL, 0, 0);
        break;
    case BLE_GATTS_EVT_WRITE: {   // the host (un)subscribed: remember it with the bond
        const ble_gatts_evt_write_t *w = &ev->evt.gatts_evt.params.write;
        if (w->handle == S.h_rep.cccd_handle && w->len >= 2) S.notify_on = w->data[0] & 1;
        if (w->handle == S.h_rep.cccd_handle || w->handle == S.h_bat.cccd_handle) sa_capture(ch);
        break;
    }
    // requests the SoftDevice expects an answer to
    case BLE_GAP_EVT_PHY_UPDATE_REQUEST: {
        ble_gap_phys_t p = {BLE_GAP_PHY_AUTO, BLE_GAP_PHY_AUTO};
        sd_ble_gap_phy_update(ch, &p);
        break;
    }
    case BLE_GAP_EVT_DATA_LENGTH_UPDATE_REQUEST:
        sd_ble_gap_data_length_update(ch, NULL, NULL);
        break;
    case BLE_GATTS_EVT_EXCHANGE_MTU_REQUEST:
        sd_ble_gatts_exchange_mtu_reply(ch, BLE_GATT_ATT_MTU_DEFAULT);
        break;
    case BLE_GAP_EVT_TIMEOUT:
    case BLE_GATTS_EVT_TIMEOUT:
        sd_ble_gap_disconnect(ch, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
        break;
    default:
        break;
    }
}

static uint32_t send_report(const uint8_t *rep) {   // 7 bytes: buttons, X (int16), Y (int16), wheel, pan
    if (S.conn == BLE_CONN_HANDLE_INVALID) return NRF_ERROR_INVALID_STATE;
    memcpy(S.rep, rep, 7);
    uint16_t len = 7;
    ble_gatts_hvx_params_t hp;
    memset(&hp, 0, sizeof hp);
    hp.handle = S.h_rep.value_handle;
    hp.type = BLE_GATT_HVX_NOTIFICATION;
    hp.p_len = &len;
    hp.p_data = S.rep;
    return sd_ble_gatts_hvx(S.conn, &hp);
}

// Battery Service: the stock battery code keeps its percentage in 0x20003076 (ADC average -> lookup table, smoothed).
// It restarts at 100 on boot and on charger changes, then settles within ~25 s; the host sees those steps too.
static void battery_poll(void) {
    uint8_t v = *(volatile uint8_t *)0x20003076;
    if (!v || v > 100 || v == S.bat) return;
    S.bat = v;
    if (S.conn == BLE_CONN_HANDLE_INVALID) return;
    uint16_t len = 1;
    ble_gatts_hvx_params_t hp;
    memset(&hp, 0, sizeof hp);
    hp.handle = S.h_bat.value_handle;
    hp.type = BLE_GATT_HVX_NOTIFICATION;
    hp.p_len = &len;
    hp.p_data = &S.bat;
    sd_ble_gatts_hvx(S.conn, &hp);   // refused if the host did not subscribe; a read always returns S.bat
}

// ---- entry points

// Main loop. STOCK: the end of the stock main loop calls the report-flag builder (orig 0x14AE4).
// MOD: the hook calls this instead; it runs the stock builder first, then the chords, the LED overlay and (BLE mode)
// the BLE event pump. SoftDevice events are polled here, not dispatched by the stock nrf_sdh library.
#define STOCK_FLAG_BUILDER ((void (*)(void))(0x14AE4 + 0x21000 + 1))   // relocated address, Thumb bit
void blehid_tick(void) {
    STOCK_FLAG_BUILDER();
    chords_poll();
    led_tick();
    if (!SD_FLAG) return;   // RF mode: nothing else
    flash_step();
    for (int i = 0; i < 8; i++) {
        uint16_t len = sizeof S.evt_buf;
        if (sd_ble_evt_get((uint8_t *)S.evt_buf, &len) != NRF_SUCCESS) break;
        on_evt((const ble_evt_t *)S.evt_buf);
    }
    battery_poll();
}

// Mouse report from the stock report builder (BLE mode only, called by REPORT_T in mk_ble.py).
// b = stock report buffer 0x200035E5: [0] buttons [1] wheel [2:3] X [4:5] Y [6] pan.
// Return 1 = "sent": the stock code clears its X/Y/wheel accumulators. 0 = "busy": it keeps accumulating and retries on the
// next pass (the stock behaviour for a busy transport), which also limits the rate to what the connection carries.
// With no subscribed host the report is dropped (1), so motion made while disconnected is not replayed later.
uint32_t blehid_tx_stock(const uint8_t *b) {
    if (S.conn == BLE_CONN_HANDLE_INVALID || !S.notify_on) return 1;
    uint8_t r[7] = {b[0], b[2], b[3], b[4], b[5], b[1], b[6]};   // HID order: buttons, X, Y, wheel, pan
    return send_report(r) == NRF_ERROR_RESOURCES ? 0 : 1;          // SoftDevice queue full: retry; sent or refused: done
}

// Exported entry table, first 16 bytes of the blob (read by mk_ble.py): init (BLE), tick, init (RF), mouse report.
__attribute__((section(".entry"), used)) const uint32_t ENTRY[4] = {
    (uint32_t)blehid_init, (uint32_t)blehid_tick, (uint32_t)blehid_init_nosd, (uint32_t)blehid_tx_stock};
