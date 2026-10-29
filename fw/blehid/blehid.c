// blehid.c — minimal BLE HID-over-GATT mouse peripheral for the relocated Model O Pro app.
// Runs in the app's main context. Entry points are exported through the table at the start of the image
// (see ENTRY below): init() once after sd_ble_enable, poll() once per main-loop iteration.
#include <stdint.h>
#include <stddef.h>
#include "ble.h"
#include "ble_gap.h"
#include "ble_gatts.h"
#include "ble_hci.h"
#include "nrf_soc.h"
#include "nrf_error.h"

#ifndef STOP_AT
#define STOP_AT 99
#endif
#define STOP(k) if (STOP_AT == (k)) { LOG[1] = 0x2000 | (k); return 0; }
#define CHORD_P0_DEFAULT ((1u << 9) | (1u << 10))   // BACK P0.9 + FORWARD P0.10 (active low)
#define CHORD_P1_DEFAULT (1u << 0)                    // DPI P1.0
#define PAIR_P1_DEFAULT ((1u << 15) | (1u << 13) | (1u << 0))   // force re-pair chord: LEFT P1.15 + RIGHT P1.13 + DPI P1.0
#define NAME "Model O PRO Wireless"
#define APPEARANCE_MOUSE 0x03C2
#define LOG ((volatile uint32_t *)0x2003F100)   // post-mortem log: [0]=magic [1]=init stage/err [2]=evt count [3..]=last evt ids ring

// ---- libc bits the compiler may call
void *memset(void *d, int c, size_t n) { uint8_t *p = d; while (n--) *p++ = (uint8_t)c; return d; }
void *memcpy(void *d, const void *s, size_t n) { uint8_t *p = d; const uint8_t *q = s; while (n--) *p++ = *q++; return d; }
void __aeabi_memcpy(void *d, const void *s, size_t n) { memcpy(d, s, n); }   // the compiler turns larger struct copies into these
void __aeabi_memcpy4(void *d, const void *s, size_t n) { memcpy(d, s, n); }
void __aeabi_memcpy8(void *d, const void *s, size_t n) { memcpy(d, s, n); }
int memcmp(const void *a, const void *b, size_t n) { const uint8_t *p = a, *q = b; while (n--) { if (*p != *q) return *p - *q; p++; q++; } return 0; }

static const uint8_t report_map_rom[] = {
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x01, 0x09, 0x01, 0xA1, 0x00,   // Mouse, Report ID 1, Pointer
    0x05, 0x09, 0x19, 0x01, 0x29, 0x08, 0x15, 0x00, 0x25, 0x01, 0x95, 0x08, 0x75, 0x01, 0x81, 0x02,  // 8 buttons
    0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x16, 0x01, 0x80, 0x26, 0xFF, 0x7F, 0x75, 0x10, 0x95, 0x02, 0x81, 0x06,  // X,Y int16 rel
    0x09, 0x38, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06,   // wheel
    0x05, 0x0C, 0x0A, 0x38, 0x02, 0x95, 0x01, 0x81, 0x06,                     // AC pan
    0xC0, 0xC0};

typedef struct {
    uint16_t conn;
    uint8_t adv_handle;
    uint8_t notify_on;
    uint8_t bonded;
    ble_gatts_char_handles_t h_rep, h_map, h_info, h_ctrl, h_proto, h_bat;
    uint16_t svc_hid, svc_bas, svc_dis;
    uint8_t map[sizeof(report_map_rom)];
    uint8_t proto, bat, rep[7], info[4], ctrl;
    uint8_t rep_ref[2], pnp[7];
    ble_gap_enc_key_t own_enc, peer_enc;
    ble_gap_id_key_t peer_id;
    ble_gap_sec_keyset_t keyset;
    ble_gap_adv_data_t adv;
    uint8_t adv_buf[31], rsp_buf[31];
    ble_gap_adv_params_t advp;
    uint32_t evt_buf[64];   // 256 B, word aligned
    uint16_t sa_len;
    uint8_t dirty, reconn, reset_after_flash, chord_on;
    uint32_t chord_p0, chord_p1, chord_t0;   // button chord (GPIO IN masks, active low) -> mode switch
    uint8_t slow, hf_released;
    uint32_t last_tx, hf_t0;
    uint8_t pair_on, fl2_n;
    uint32_t pair_t0, fl2_addr, fl2_buf[4];
    uint8_t neutral_pending, usb_prev, led_state, led_color, led_blinks;   // release-all report / USB edge / mode LED
    uint16_t led_orig[3];
    uint32_t led_t0, bat_t0;
    uint8_t bat_cand;
    uint8_t slot;            // bond slot of the connected/last host (0xFF = none)
    uint8_t pairing, prev_target, ac_state, target, hc_state, hc_dir, id_ok;   // host selected for advertising (slot or HOST_NEW) / host-switch chord state / S.id valid
    uint32_t hc_t0, ac_t0, pair_win_t0, pair_blink_t0, nonce, new_nonce, sw_t0;
    uint32_t img[256];       // RAM mirror of the bond area (4 slots x 64 words): every decision reads this, never the flash page being rewritten
    uint8_t sw_pending;      // host selection changed, link not yet moved (debounce)
    ble_gap_id_key_t id;     // identity (IRK + address) of the host in S.slot
    uint16_t slot_seq;       // its pairing sequence number
    uint8_t sa[88];          // GATT system attributes (CCCD state) of the bonded peer
    struct { uint8_t state, tries, err; uint32_t addr, words; uint32_t buf[256]; } fl;   // async flash writer (SD flash API)
} state_t;

static state_t S;

static void sys_reset(void);
uint32_t blehid_send(const uint8_t *rep);
#define RTC1_COUNTER (*(volatile uint32_t *)0x40011504)   // 32768 Hz, free running (app timer base)
// Battery level hand-off. The stock battery code resets its percentage to 100 on every charger-state change and at boot, then slews it
// down to the real level (~25 s). Publishing that transient made hosts show wrong values (e.g. 50 % while the real level was 36 %).
// So: publish only after the stock value has been stable for BAT_STABLE_TICKS, and remember the last published value in RAM (kept
// across soft resets: WDT, mode switch, reflash) so a reset does not re-announce the startup 100.
#define BAT_KEEP ((volatile uint32_t *)0x2003F0E0)   // [0] magic, [1] level, [2] ~level
#define BAT_MAGIC 0xBA770001u
#define BAT_STABLE_TICKS (30u * 32768u)
// Idle time before the stock sleep path runs, in seconds (stock default 420 = 7 min; CORE has no setting for it). The stock idle
// callback compares its 1 Hz idle counter with the u16 at 0x200038CB.
#define BLE_SLEEP_S 420u
static uint8_t bat_restore(void) {
    if (BAT_KEEP[0] == BAT_MAGIC && (BAT_KEEP[1] ^ BAT_KEEP[2]) == 0xFFFFFFFFu && BAT_KEEP[1] <= 100) return (uint8_t)BAT_KEEP[1];
    uint8_t v = *(volatile uint8_t *)0x20003076;
    return v > 100 ? 100 : v;
}
static void bat_keep(uint8_t v) { BAT_KEEP[1] = v; BAT_KEEP[2] = ~(uint32_t)v; BAT_KEEP[0] = BAT_MAGIC; }
static void wait_ms(uint32_t ms) { uint32_t t0 = RTC1_COUNTER; while (((RTC1_COUNTER - t0) & 0xFFFFFF) < ms * 33) {} }

// All-zero report: releases every button on the host. Windows keeps the last HID state of a BLE device that vanishes,
// so this is sent before the mouse leaves a host (mode switch, USB takes over) and when a host (re)subscribes.
static uint32_t send_neutral(void) { static const uint8_t z[7] = {0}; return blehid_send(z); }
// Leave the current BLE link cleanly before a reset: release buttons, terminate, give the radio a few events.
static void leave_link(void) {
    if (S.conn == BLE_CONN_HANDLE_INVALID) return;
    send_neutral();
    wait_ms(20);
    sd_ble_gap_disconnect(S.conn, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
    wait_ms(30);
}

// Mode indicator on the stock RGB LED: reuse the stock PWM driver, just overlay its 3 duty values (R,G,B @0x20003270)
// for a short blink pattern and put the stock values back afterwards.
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
    int on = (ms % 500) < 300;
    for (int i = 0; i < 3; i++) LED_SEQ[i] = (on && ((S.led_color >> i) & 1)) ? 0x80C0 : 0x8000;   // ~75% duty
}
// ---- bond persistence: BOND_SLOTS records of 128 B in one flash page, written through the SD flash API (whole page at a time)
#define BOND_ADDR 0xFD000u
#define BOND_MAGIC 0xB0DD0001u
#define BOND_SLOTS 4
#define BOND_STRIDE 256u          // legacy 128 B record + peer identity record
#define ID_MAGIC 0x1D1D0002u
#define HOST_NEW 0xFE             // S.target value: no host selected, advertise to anybody so a new one can pair
static uint32_t rec_sum(const uint32_t *w, int n) { uint32_t a = 0x5A5A1234; while (n--) a = (a << 1 | a >> 31) ^ *w++; return a; }
// record (128 B = 32 words): [0]=magic [1]=sum(words 2..31) [2..8]=enc key (28 B) [9]=sa_len | pairing seq << 16 [10..31]=sys attrs (88 B)
// slot 0 is the single-bond record of the older firmware, so an existing bond stays valid.
// words 32..41 of a slot: [32]=ID_MAGIC [33]=sum(34..41) [34..39]=peer identity (ble_gap_id_key_t, 23 B) [40]=address nonce [41]=identity valid;
// absent in a legacy record (nonce 0, no identity). Every stored host has its own advertising address (generation + nonce), so a host only
// ever finds the mouse while its slot is the selected one, and a pairing window advertises from a fresh address nobody has stored.
static const uint32_t *slot_rec(int i) { return S.img + (BOND_STRIDE / 4) * i; }   // the RAM mirror (flash is only written, and read at boot)
static int slot_valid(int i) { const uint32_t *w = slot_rec(i); return w[0] == BOND_MAGIC && w[1] == rec_sum(w + 2, 30); }
static int id_rec_ok(int i) { const uint32_t *w = slot_rec(i) + 32; return w[0] == ID_MAGIC && w[1] == rec_sum(w + 2, 8); }
static int slot_has_id(int i) { return id_rec_ok(i) && slot_rec(i)[41]; }
static uint32_t slot_nonce(int i) { return id_rec_ok(i) ? slot_rec(i)[40] : 0; }
static uint32_t next_nonce(void) { uint32_t m = 0; for (int i = 0; i < BOND_SLOTS; i++) if (slot_valid(i) && slot_nonce(i) > m) m = slot_nonce(i); return m + 1; }
static uint16_t slot_seq_of(int i) { return (uint16_t)(slot_rec(i)[9] >> 16); }
static void slot_load(int i) {
    const uint32_t *w = slot_rec(i);
    memcpy(&S.own_enc, w + 2, sizeof S.own_enc);
    S.sa_len = (uint16_t)w[9];
    if (S.sa_len > sizeof S.sa) S.sa_len = 0;
    memcpy(S.sa, w + 10, sizeof S.sa);
    S.id_ok = (uint8_t)slot_has_id(i); S.nonce = slot_nonce(i);
    if (S.id_ok) memcpy(&S.id, w + 34, sizeof S.id);
    S.slot = (uint8_t)i; S.slot_seq = slot_seq_of(i);
    S.bonded = 1;
}
static void bond_load(void) {
    int best = -1;
    memcpy(S.img, (const void *)BOND_ADDR, sizeof S.img);
    S.slot = 0xFF;
    for (int i = 0; i < BOND_SLOTS; i++)
        if (slot_valid(i) && (best < 0 || slot_seq_of(i) > slot_seq_of(best))) best = i;
    if (best >= 0) slot_load(best);   // most recently paired host
}
// a new pairing: first free slot, else the oldest one; the new record gets the highest sequence number
// A host that is already stored (same identity address or IRK) gets its own slot back instead of a second one.
static void slot_alloc(const ble_gap_id_key_t *id) {
    int s = -1, same = -1; uint16_t top = 0;
    for (int i = 0; i < BOND_SLOTS; i++) {
        if (!slot_valid(i)) { if (s < 0 || slot_valid(s)) s = i; continue; }
        if (slot_seq_of(i) > top) top = slot_seq_of(i);
        if (s < 0 || (slot_valid(s) && slot_seq_of(i) < slot_seq_of(s))) s = i;
        if (id && slot_has_id(i)) {
            const ble_gap_id_key_t *k = (const ble_gap_id_key_t *)(slot_rec(i) + 34);
            if (memcmp(k->id_info.irk, id->id_info.irk, 16) == 0 || (k->id_addr_info.addr_type == id->id_addr_info.addr_type && memcmp(k->id_addr_info.addr, id->id_addr_info.addr, 6) == 0)) same = i;
        }
    }
    if (same >= 0) s = same;
    LOG[0x2B] = (uint32_t)s << 8 | (same >= 0);
    S.slot = (uint8_t)s; S.slot_seq = (uint16_t)(top + 1);
}
static void flash_request(uint32_t addr, const uint32_t *words, uint32_t n) {
    memcpy(S.fl.buf, words, n * 4);
    S.fl.addr = addr; S.fl.words = n; S.fl.tries = 0; S.fl.err = 0; S.fl.state = 1;
}
static void bond_flush(void);
static void flash_step(void) {
    uint32_t r;
    if ((S.fl.state == 0 || S.fl.state >= 8) && S.dirty) { S.dirty = 0; bond_flush(); }
    switch (S.fl.state) {
    case 1:   // erase
        r = sd_flash_page_erase(S.fl.addr / 4096);
        if (r == 0) S.fl.state = 2; else if (r != NRF_ERROR_BUSY) { S.fl.err = (uint8_t)r; S.fl.state = 9; }
        break;
    case 2:   // write (BUSY until the erase finished)
        r = sd_flash_write((uint32_t *)S.fl.addr, S.fl.buf, S.fl.words);
        if (r == 0) { S.fl.state = 3; S.fl.tries = 0; } else if (r != NRF_ERROR_BUSY) { S.fl.err = (uint8_t)r; S.fl.state = 9; }
        break;
    case 3:   // verify after a few ticks
        if (++S.fl.tries > 30) {
            S.fl.state = memcmp((void *)S.fl.addr, S.fl.buf, S.fl.words * 4) == 0 ? 0 : 8;
            LOG[0x22] = S.fl.state;
            if (S.fl.state == 0 && S.fl2_n) {   // chained second request (force re-pair: config generation, then bond erase)
                uint8_t n = S.fl2_n; S.fl2_n = 0;
                flash_request(S.fl2_addr, S.fl2_buf, n);
                break;
            }
            if (S.fl.state == 0 && S.reset_after_flash) { leave_link(); sys_reset(); }
            S.reset_after_flash = 0;
        }
        break;
    default:
        break;
    }
}
static void img_store(void) {   // working copy of the connected host's record -> RAM mirror
    uint32_t *r = S.img + (BOND_STRIDE / 4) * S.slot;
    memset(r, 0, BOND_STRIDE);
    memcpy(r + 2, &S.own_enc, sizeof S.own_enc);
    r[9] = S.sa_len | ((uint32_t)S.slot_seq << 16);
    memcpy(r + 10, S.sa, sizeof S.sa);
    r[0] = BOND_MAGIC;
    r[1] = rec_sum(r + 2, 30);
    if (S.id_ok) memcpy(r + 34, &S.id, sizeof S.id);
    r[32] = ID_MAGIC; r[40] = S.nonce; r[41] = S.id_ok; r[33] = rec_sum(r + 34, 8);
}
static void bond_flush(void) {   // the whole mirror goes to flash (erase + write, asynchronous); nothing reads the flash copy meanwhile
    memcpy(S.fl.buf, S.img, sizeof S.img);
    S.fl.addr = BOND_ADDR; S.fl.words = sizeof S.img / 4; S.fl.tries = 0; S.fl.err = 0; S.fl.state = 1;
    LOG[0x28] = S.slot;
}
static void bond_save(void) { if (S.slot >= BOND_SLOTS) return; img_store(); S.dirty = 1; }
// fetch the peer's system attributes (CCCDs) from the SD and persist them with the bond
static void sa_capture_and_save(uint16_t conn) {
    uint16_t len = sizeof S.sa;
    if (sd_ble_gatts_sys_attr_get(conn, S.sa, &len, BLE_GATTS_SYS_ATTR_FLAG_SYS_SRVCS | BLE_GATTS_SYS_ATTR_FLAG_USR_SRVCS) == 0) {
        S.sa_len = len;
        if (S.slot < BOND_SLOTS) bond_save();
    }
}

// ---- persistent transport mode (BLE = SoftDevice on, DONGLE = vendor 2.4G/USB firmware, SoftDevice off), chosen at boot
#define CFG_ADDR 0xFE000u
#define CFG_MAGIC 0xC0DE0001u
#define MODE_BLE 1
#define MODE_DONGLE 2
#define SD_FLAG (*(volatile uint8_t *)0x20003830)   // nrf_sdh "enabled"
static uint32_t cfg_mode(void) {
    const uint32_t *w = (const uint32_t *)CFG_ADDR;
    if (w[0] == CFG_MAGIC && (w[1] ^ w[2]) == 0xFFFFFFFFu && (w[1] == MODE_BLE || w[1] == MODE_DONGLE)) return w[1];
    return MODE_BLE;
}
static void sys_reset(void) {
    __asm volatile("dsb");
    *(volatile uint32_t *)0xE000ED0C = 0x05FA0004;
    for (;;) {}
}
#define NVMC_READY (*(volatile uint32_t *)0x4001E400)
#define NVMC_CONFIG (*(volatile uint32_t *)0x4001E504)
#define NVMC_ERASEPAGE (*(volatile uint32_t *)0x4001E508)
static void nvmc_store(uint32_t addr, const uint32_t *w, int n) {   // only with the SoftDevice DISABLED
    NVMC_CONFIG = 2; NVMC_ERASEPAGE = addr; while (!NVMC_READY) {}
    NVMC_CONFIG = 1;
    for (int i = 0; i < n; i++) { *(volatile uint32_t *)(addr + 4 * i) = w[i]; while (!NVMC_READY) {} }
    NVMC_CONFIG = 0; while (!NVMC_READY) {}
}
// pairing generation (config word 3): bumped by "force re-pair"; changes the BLE address so hosts treat the mouse as a new device
static uint32_t cfg_gen(void) {
    const uint32_t *w = (const uint32_t *)CFG_ADDR;
    if (w[0] == CFG_MAGIC && (w[1] ^ w[2]) == 0xFFFFFFFFu && w[3] != 0xFFFFFFFFu) return w[3];
    return 0;
}
static void mode_switch(void) {
    uint32_t cur = cfg_mode(), nxt = cur == MODE_BLE ? MODE_DONGLE : MODE_BLE;
    uint32_t rec[4] = {CFG_MAGIC, nxt, ~nxt, cfg_gen()};
    LOG[0x25] = nxt;
    if (SD_FLAG) send_neutral();
    if (SD_FLAG) { S.reset_after_flash = 1; flash_request(CFG_ADDR, rec, 4); }
    else { nvmc_store(CFG_ADDR, rec, 4); sys_reset(); }
}
// Force re-pairing: forget the bond and move to a new BLE address (pairing generation + 1), then reset. The host that
// still holds the old pairing sees a different device and no stale key is ever replayed.
static void pair_reset(void) {
    uint32_t m = cfg_mode();
    uint32_t cfg[4] = {CFG_MAGIC, m, ~m, cfg_gen() + 1};
    static const uint32_t none[4] = {0, 0, 0, 0};
    LOG[0x26] = cfg[3];
    send_neutral();
    memcpy(S.fl2_buf, none, 16); S.fl2_addr = BOND_ADDR; S.fl2_n = 4;
    S.reset_after_flash = 1;
    flash_request(CFG_ADDR, cfg, 4);
}
// button chord: held for ~3 s (RTC1 @32768 Hz) toggles the mode. Masks are runtime-settable (default: none = disabled).
static void chord_poll(void) {
    if (!(S.chord_p0 | S.chord_p1)) return;
    uint32_t in0 = *(volatile uint32_t *)0x50000510, in1 = *(volatile uint32_t *)0x50000810;
    int down = ((~in0 & S.chord_p0) == S.chord_p0) && ((~in1 & S.chord_p1) == S.chord_p1);
    uint32_t now = RTC1_COUNTER;
    if (!down) { S.chord_on = 0; return; }
    if (!S.chord_on) { S.chord_on = 1; S.chord_t0 = now; return; }
    if (((now - S.chord_t0) & 0xFFFFFF) > 98304) { S.chord_on = 0; mode_switch(); }
}
// Host switching: DPI + exactly one of FORWARD (next) / BACK (previous), held for 1 s. Cycles through the stored hosts only, in slot
// order, wrapping around. The current host is dropped and the mouse advertises to the new one only.
static void adv_restart(int fast);
static void adv_reopen(void) {   // restart advertising with the filter for S.target (not while connected)
    LOG[0x35] = sd_ble_gap_adv_stop(S.adv_handle);
    adv_restart(1);
}
static void host_switch(int dir) {   // only moves the selection; host_switch_apply() moves the link once the user stopped pressing
    uint8_t list[BOND_SLOTS]; int n = 0, pos = 0;
    for (int i = 0; i < BOND_SLOTS; i++) if (slot_valid(i)) { if (i == S.target) pos = n; list[n++] = (uint8_t)i; }
    if (n < 2) return;
    uint8_t t = list[(pos + n + dir) % n];
    LOG[0x2A] = t;
    S.pairing = 0;
    S.target = t;
    S.sw_pending = 1; S.sw_t0 = RTC1_COUNTER;
    led_start(4, (uint8_t)(t + 1));
}
#define SWITCH_DEBOUNCE_TICKS 49152u   // 1.5 s
// Make slot t the working record and "last used" (highest sequence number = the boot choice). Only while no host is connected, so a late
// CCCD write of the old host can never be saved into the new host's record.
static void select_slot(uint8_t t) {
    uint16_t top = 0;
    for (int i = 0; i < BOND_SLOTS; i++) if (slot_valid(i) && slot_seq_of(i) > top) top = slot_seq_of(i);
    slot_load(t);
    if (slot_seq_of(t) != top) { S.slot_seq = (uint16_t)(top + 1); bond_save(); }
}
static void host_switch_apply(void) {
    if (!S.sw_pending || ((RTC1_COUNTER - S.sw_t0) & 0xFFFFFF) < SWITCH_DEBOUNCE_TICKS) return;
    S.sw_pending = 0;
    uint8_t t = S.target;
    if (t >= BOND_SLOTS || !slot_valid(t)) return;
    if (S.conn != BLE_CONN_HANDLE_INVALID) {
        if (S.slot == t) return;   // already on that host
        send_neutral();
        leave_link();              // the DISCONNECTED event selects the slot and restarts advertising from its address
    } else {
        select_slot(t);
        adv_reopen();
    }
}
static void host_chord_poll(void) {
    uint32_t in0 = *(volatile uint32_t *)0x50000510, in1 = *(volatile uint32_t *)0x50000810;
    int dpi = !(in1 & 1), fwd = !(in0 & (1u << 10)), back = !(in0 & (1u << 9)), lft = !(in1 & (1u << 15)), rgt = !(in1 & (1u << 13));
    uint32_t now = RTC1_COUNTER;
    if (!(dpi && (fwd ^ back) && !lft && !rgt)) { S.hc_state = 0; return; }
    if (S.hc_state == 0) { S.hc_state = 1; S.hc_t0 = now; S.hc_dir = fwd ? 1 : 0; return; }
    if (S.hc_state == 1 && ((now - S.hc_t0) & 0xFFFFFF) > 32768) { S.hc_state = 2; host_switch(S.hc_dir ? 1 : -1); }
}
// Adding a host: DPI + LEFT held for 3 s opens a 120 s pairing window (purple blink every 2 s while it is open) (open advertising, pairing accepted). A host that is already
// stored gets its own slot back, a new one takes a free slot (or replaces the oldest). Pairing is refused outside the window.
#define PAIR_WINDOW_TICKS (120u * 32768u)
static void pair_window_open(void) {
    send_neutral();
    S.pairing = 1; S.sw_pending = 0; S.pair_win_t0 = S.pair_blink_t0 = RTC1_COUNTER;
    S.prev_target = S.target; S.target = HOST_NEW; S.new_nonce = next_nonce();
    led_start(5, 2);
    if (S.conn != BLE_CONN_HANDLE_INVALID) leave_link();
    else adv_reopen();
}
static void pair_window_poll(void) {   // closes the window after 120 s; a finished pairing closes it too (AUTH_STATUS)
    if (!S.pairing) return;
    uint32_t now = RTC1_COUNTER;
    if (!S.led_state && ((now - S.pair_blink_t0) & 0xFFFFFF) > 65536) { S.pair_blink_t0 = now; led_start(5, 1); }
    if (((now - S.pair_win_t0) & 0xFFFFFF) < PAIR_WINDOW_TICKS) return;
    S.pairing = 0;
    int any = 0;
    for (int i = 0; i < BOND_SLOTS; i++) any |= slot_valid(i);
    if (!any) return;                                   // nothing stored: stay open
    S.target = S.prev_target < BOND_SLOTS && slot_valid(S.prev_target) ? S.prev_target : 0;
    if (S.conn == BLE_CONN_HANDLE_INVALID) adv_reopen();   // connected (mid-pairing): leave it, the filter applies at the next restart
}
static void add_chord_poll(void) {
    uint32_t in0 = *(volatile uint32_t *)0x50000510, in1 = *(volatile uint32_t *)0x50000810;
    int dpi = !(in1 & 1), lft = !(in1 & (1u << 15)), rgt = !(in1 & (1u << 13)), fb = !(in0 & (1u << 10)) || !(in0 & (1u << 9));
    uint32_t now = RTC1_COUNTER;
    if (!(dpi && lft && !rgt && !fb)) { S.ac_state = 0; return; }
    if (S.ac_state == 0) { S.ac_state = 1; S.ac_t0 = now; return; }
    if (S.ac_state == 1 && ((now - S.ac_t0) & 0xFFFFFF) > 98304) { S.ac_state = 2; pair_window_open(); }
}
static void pair_chord_poll(void) {
    if (!SD_FLAG) return;
    uint32_t in1 = *(volatile uint32_t *)0x50000810;
    if ((~in1 & PAIR_P1_DEFAULT) != PAIR_P1_DEFAULT) { S.pair_on = 0; return; }
    uint32_t now = RTC1_COUNTER;
    if (!S.pair_on) { S.pair_on = 1; S.pair_t0 = now; return; }
    if (((now - S.pair_t0) & 0xFFFFFF) > 327680) { S.pair_on = 0; led_start(5, 3); pair_reset(); }   // 10 s: it erases every stored host
}

static void logev(uint32_t id) {
    uint32_t n = LOG[2]++;
    LOG[3 + (n & 15)] = id;
}

// ---- GATT helpers
static void sec_mode(ble_gap_conn_sec_mode_t *m, int enc) {
    if (enc) BLE_GAP_CONN_SEC_MODE_SET_ENC_NO_MITM(m); else BLE_GAP_CONN_SEC_MODE_SET_OPEN(m);
}

static uint32_t add_char(uint16_t svc, uint16_t uuid16, int props, int rd_enc, int wr_enc, uint8_t *val, uint16_t len,
                         uint16_t maxlen, ble_gatts_char_handles_t *h) {
    ble_uuid_t uuid = {uuid16, BLE_UUID_TYPE_BLE};
    ble_gatts_char_md_t cmd;
    ble_gatts_attr_md_t amd;
    ble_gatts_attr_t attr;
    memset(&cmd, 0, sizeof cmd);
    memset(&amd, 0, sizeof amd);
    memset(&attr, 0, sizeof attr);
    cmd.char_props.read = (props & 1) != 0;
    cmd.char_props.write_wo_resp = (props & 2) != 0;
    cmd.char_props.write = (props & 4) != 0;
    cmd.char_props.notify = (props & 8) != 0;
    sec_mode(&amd.read_perm, rd_enc);
    sec_mode(&amd.write_perm, wr_enc);
    amd.vloc = BLE_GATTS_VLOC_USER;       // value lives in S (RAM): keeps the tiny attribute table free
    attr.p_uuid = &uuid;
    attr.p_attr_md = &amd;
    attr.init_len = len;
    attr.max_len = maxlen;
    attr.p_value = val;
    ble_gatts_attr_md_t cccd;
    memset(&cccd, 0, sizeof cccd);
    if (props & 8) {
        BLE_GAP_CONN_SEC_MODE_SET_OPEN(&cccd.read_perm);
        sec_mode(&cccd.write_perm, wr_enc);
        cccd.vloc = BLE_GATTS_VLOC_STACK;
        cmd.p_cccd_md = &cccd;
    }
    return sd_ble_gatts_characteristic_add(svc, &cmd, &attr, h);
}

static uint32_t add_desc_ref(uint16_t char_handle, uint8_t *val) {   // Report Reference (0x2908)
    ble_uuid_t uuid = {0x2908, BLE_UUID_TYPE_BLE};
    ble_gatts_attr_md_t amd;
    ble_gatts_attr_t attr;
    uint16_t h;
    memset(&amd, 0, sizeof amd);
    memset(&attr, 0, sizeof attr);
    sec_mode(&amd.read_perm, 1);
    BLE_GAP_CONN_SEC_MODE_SET_NO_ACCESS(&amd.write_perm);
    amd.vloc = BLE_GATTS_VLOC_USER;
    attr.p_uuid = &uuid;
    attr.p_attr_md = &amd;
    attr.init_len = 2;
    attr.max_len = 2;
    attr.p_value = val;
    return sd_ble_gatts_descriptor_add(char_handle, &attr, &h);
}

static uint32_t add_service(uint16_t uuid16, uint16_t *h) {
    ble_uuid_t uuid = {uuid16, BLE_UUID_TYPE_BLE};
    return sd_ble_gatts_service_add(BLE_GATTS_SRVC_TYPE_PRIMARY, &uuid, h);
}

static uint32_t start_adv(void) {
    return sd_ble_gap_adv_start(S.adv_handle, BLE_CONN_CFG_TAG_DEFAULT);
}
// Advertising power policy: 50 ms for 30 s after boot/disconnect (quick reconnect), then 500 ms until a host connects.
// Advertising address = f(pairing generation, nonce of the selected slot); HOST_NEW uses the next unused nonce. Call only while not advertising.
static void adv_addr(void) {
    uint32_t gen = cfg_gen(), n = S.target < BOND_SLOTS ? slot_nonce(S.target) : S.new_nonce;
    if (!(gen | n)) return;
    uint32_t lo = *(volatile uint32_t *)0x100000A4 ^ (gen * 0x9E3779B1u) ^ (n * 0x85EBCA6Bu), hi = *(volatile uint32_t *)0x100000A8;
    ble_gap_addr_t a;
    memset(&a, 0, sizeof a);
    a.addr_type = BLE_GAP_ADDR_TYPE_RANDOM_STATIC;
    a.addr[0] = (uint8_t)lo; a.addr[1] = (uint8_t)(lo >> 8); a.addr[2] = (uint8_t)(lo >> 16); a.addr[3] = (uint8_t)(lo >> 24);
    a.addr[4] = (uint8_t)hi; a.addr[5] = (uint8_t)((hi >> 8) | 0xC0);
    LOG[0x27] = sd_ble_gap_addr_set(&a);
    LOG[0x2E] = lo; LOG[0x2F] = (uint32_t)S.target << 8 | n;   // test visibility: address seed, selected slot / nonce
}
static void adv_restart(int fast) {
    adv_addr();
    S.advp.interval = fast ? 0x30 : 800;   // fast: 30 ms for 60 s (a host's reconnect scan gets many chances), then 500 ms
    S.advp.duration = fast ? 6000 : 0;
    LOG[0x36] = sd_ble_gap_adv_set_configure(&S.adv_handle, &S.adv, &S.advp);
    LOG[0x37] = LOG[0x36] ? 0xFFFF : start_adv();
    LOG[0x2B]++;   // advertising restarts since boot (the three words above hold the last return codes)
    {   // what the SoftDevice really advertises: address (LOG[0x3D], LOG[0x3E]) and the call's return code (LOG[0x3F])
        ble_gap_addr_t ca; memset(&ca, 0, sizeof ca);
        LOG[0x3F] = sd_ble_gap_adv_addr_get(S.adv_handle, &ca);
        LOG[0x3D] = ca.addr[0] | ca.addr[1] << 8 | ca.addr[2] << 16 | (uint32_t)ca.addr[3] << 24;
        LOG[0x3E] = ca.addr[4] | ca.addr[5] << 8 | (uint32_t)ca.addr_type << 16;
    }
}

// DONGLE mode (no SoftDevice): only state/chord support
uint32_t blehid_init_nosd(void) {
    memset(&S, 0, sizeof S);
    led_start(2, 2);           // boot indicator: 2.4G dongle = 2 green blinks
    LOG[0] = 0xB1E0A002;
    LOG[2] = 0;
    S.conn = BLE_CONN_HANDLE_INVALID;
    S.chord_p0 = CHORD_P0_DEFAULT; S.chord_p1 = CHORD_P1_DEFAULT;
    return 0;
}

// ---- init: returns 0 or the first failing SD error (stage in LOG[1])
uint32_t blehid_init(void) {
    uint32_t e;
    LOG[0] = 0xB1E0A001;
    LOG[2] = 0;
    memset(&S, 0, sizeof S);   // .bss lives in uninitialised RAM (nobody zeroes it)
    for (int i = 0x30; i < 0x40; i++) LOG[i] = 0;
    S.hf_t0 = RTC1_COUNTER;
    LOG[0x20] = LOG[0x21] = LOG[0x22] = 0;
    bond_load();
    S.target = S.slot < BOND_SLOTS ? S.slot : HOST_NEW;
    S.new_nonce = next_nonce();
    S.chord_p0 = CHORD_P0_DEFAULT; S.chord_p1 = CHORD_P1_DEFAULT;
    led_start(S.bonded ? 4 : 5, 2);   // boot indicator: BLE = 2 blue blinks, 2 purple blinks while unpaired (pairing mode)
    LOG[0x23] = S.bonded;
    LOG[0x24] = 0xEEEE;
    S.conn = BLE_CONN_HANDLE_INVALID;
    memcpy(S.map, report_map_rom, sizeof S.map);
    S.proto = 1;
    *(volatile uint16_t *)0x200038CB = BLE_SLEEP_S;
    S.bat = bat_restore();   // last published level (survives soft resets); else the stock byte, which starts at 100 and settles within ~30 s
    S.info[0] = 0x11; S.info[1] = 0x01; S.info[2] = 0; S.info[3] = 0x02;   // bcdHID 1.11, country 0, flags: normally connectable
    S.rep_ref[0] = 1; S.rep_ref[1] = 1;                                    // Report ID 1, Input

    STOP(1)
    ble_gap_conn_sec_mode_t sm;
    BLE_GAP_CONN_SEC_MODE_SET_OPEN(&sm);
    if ((e = sd_ble_gap_device_name_set(&sm, (const uint8_t *)NAME, sizeof NAME - 1))) { LOG[1] = 0x100 | 1; return e; }
    if ((e = sd_ble_gap_appearance_set(APPEARANCE_MOUSE))) { LOG[1] = 0x100 | 2; return e; }
    ble_gap_conn_params_t cp = {6, 12, 0, 400};
    if ((e = sd_ble_gap_ppcp_set(&cp))) { LOG[1] = 0x100 | 3; return e; }

    STOP(2)
    // Device Information: PnP ID (VID 0x258A / PID 0x2015)
    static const uint8_t pnp_rom[7] = {0x02, 0x8A, 0x25, 0x15, 0x20, 0x00, 0x01};
    memcpy(S.pnp, pnp_rom, 7);
    if ((e = add_service(0x180A, &S.svc_dis))) { LOG[1] = 0x100 | 4; return e; }
    ble_gatts_char_handles_t hd;
    if ((e = add_char(S.svc_dis, 0x2A50, 1, 0, 0, S.pnp, 7, 7, &hd))) { LOG[1] = 0x100 | 5; return e; }
    STOP(3)
    // Battery
    if ((e = add_service(0x180F, &S.svc_bas))) { LOG[1] = 0x100 | 6; return e; }
    if ((e = add_char(S.svc_bas, 0x2A19, 1 | 8, 0, 0, &S.bat, 1, 1, &S.h_bat))) { LOG[1] = 0x100 | 7; return e; }
    STOP(4)
    // HID
    if ((e = add_service(0x1812, &S.svc_hid))) { LOG[1] = 0x100 | 8; return e; }
    if ((e = add_char(S.svc_hid, 0x2A4A, 1, 1, 1, S.info, 4, 4, &S.h_info))) { LOG[1] = 0x100 | 9; return e; }
    if ((e = add_char(S.svc_hid, 0x2A4B, 1, 1, 1, S.map, sizeof S.map, sizeof S.map, &S.h_map))) { LOG[1] = 0x100 | 10; return e; }
    if ((e = add_char(S.svc_hid, 0x2A4C, 2, 1, 1, &S.ctrl, 1, 1, &S.h_ctrl))) { LOG[1] = 0x100 | 11; return e; }
    if ((e = add_char(S.svc_hid, 0x2A4E, 1 | 2, 1, 1, &S.proto, 1, 1, &S.h_proto))) { LOG[1] = 0x100 | 12; return e; }
    if ((e = add_char(S.svc_hid, 0x2A4D, 1 | 8, 1, 1, S.rep, 7, 7, &S.h_rep))) { LOG[1] = 0x100 | 13; return e; }
    if ((e = add_desc_ref(S.h_rep.value_handle, S.rep_ref))) { LOG[1] = 0x100 | 14; return e; }

    STOP(5)
    // advertising: flags + appearance + HID UUID; name in the scan response
    uint8_t *a = S.adv_buf;
    uint8_t n = 0;
    a[n++] = 2; a[n++] = 0x01; a[n++] = 0x06;
    a[n++] = 3; a[n++] = 0x19; a[n++] = APPEARANCE_MOUSE & 0xFF; a[n++] = APPEARANCE_MOUSE >> 8;
    a[n++] = 3; a[n++] = 0x03; a[n++] = 0x12; a[n++] = 0x18;
    uint8_t m = 0;
    S.rsp_buf[m++] = sizeof NAME; S.rsp_buf[m++] = 0x09;
    for (size_t i = 0; i < sizeof NAME - 1; i++) S.rsp_buf[m++] = NAME[i];
    S.adv.adv_data.p_data = S.adv_buf; S.adv.adv_data.len = n;
    S.adv.scan_rsp_data.p_data = S.rsp_buf; S.adv.scan_rsp_data.len = m;
    S.advp.properties.type = BLE_GAP_ADV_TYPE_CONNECTABLE_SCANNABLE_UNDIRECTED;
    S.advp.interval = 0x50;   // 50 ms
    S.advp.duration = 3000;   // 30 s fast (50 ms), then slow (500 ms): see adv_restart()
    S.advp.primary_phy = BLE_GAP_PHY_1MBPS;
    S.adv_handle = BLE_GAP_ADV_SET_HANDLE_NOT_SET;
    adv_addr();
    if ((e = sd_ble_gap_adv_set_configure(&S.adv_handle, &S.adv, &S.advp))) { LOG[1] = 0x100 | 15; return e; }
    if ((e = start_adv())) { LOG[1] = 0x100 | 16; return e; }
    LOG[1] = 0x1000;   // ok
    return 0;
}

static const ble_gap_sec_params_t secp = {
    .bond = 1, .mitm = 0, .lesc = 0, .keypress = 0, .io_caps = BLE_GAP_IO_CAPS_NONE, .oob = 0,
    .min_key_size = 7, .max_key_size = 16,
    .kdist_own = {.enc = 1, .id = 0, .sign = 0, .link = 0},
    .kdist_peer = {.enc = 1, .id = 1, .sign = 0, .link = 0}};

// Ask the central for the fastest connection interval (7.5 ms, no slave latency): Windows tends to ignore the PPCP values
// and keep a longer default interval, which is the main source of BLE mouse latency.
static void request_fast_conn(uint16_t ch) {
    ble_gap_conn_params_t p = {6, 6, 0, 400};
    LOG[0x33] = sd_ble_gap_conn_param_update(ch, &p);
}
// Idle (no report for 5 s): 15 ms interval + slave latency 20 lets the radio skip most connection events (data is still sent
// at the next event, latency only applies to the mouse's own listening); back to 7.5 ms / latency 0 on the first report.
static void request_slow_conn(uint16_t ch) {
    ble_gap_conn_params_t p = {12, 12, 20, 400};
    if (LOG[0x38]) { p.min_conn_interval = p.max_conn_interval = (uint16_t)LOG[0x38]; p.slave_latency = (uint16_t)LOG[0x39]; p.conn_sup_timeout = (uint16_t)(LOG[0x3B] ? LOG[0x3B] : 400); }   // live tuning hook (SWD)
    LOG[0x34] = sd_ble_gap_conn_param_update(ch, &p);
}

static void on_evt(const ble_evt_t *ev) {
    uint16_t id = ev->header.evt_id;
    uint16_t ch = ev->evt.gap_evt.conn_handle;
    logev(id);
    switch (id) {
    case BLE_GAP_EVT_CONNECTED:
        S.conn = ch;
        S.notify_on = 0;
        S.sa_len = 0; S.slot = 0xFF;   // whichever host this is, it is matched to its slot at encryption time
        LOG[0x30] = ev->evt.gap_evt.params.connected.conn_params.max_conn_interval;   // initial interval (1.25 ms units)
        LOG[0x31] = 0;
        led_start(4, 1);           // BLE connected: one blue blink
        S.last_tx = RTC1_COUNTER; S.slow = 0;
        request_fast_conn(ch);
        break;
    case BLE_GAP_EVT_ADV_SET_TERMINATED:
        if (S.conn == BLE_CONN_HANDLE_INVALID) adv_restart(0);   // fast window over: slow advertising
        break;
    case BLE_GAP_EVT_CONN_PARAM_UPDATE:
        LOG[0x31] = ev->evt.gap_evt.params.conn_param_update.conn_params.max_conn_interval;   // interval after the central's answer
        LOG[0x32] = ev->evt.gap_evt.params.conn_param_update.conn_params.slave_latency;
        break;
    case BLE_GAP_EVT_DISCONNECTED:
        S.conn = BLE_CONN_HANDLE_INVALID;
        S.notify_on = 0;
        if (S.target < BOND_SLOTS && slot_valid(S.target) && S.slot != S.target) select_slot(S.target);   // a switch was requested
        adv_restart(1);
        break;
    case BLE_GAP_EVT_SEC_PARAMS_REQUEST: {
        int any = 0;
        for (int i = 0; i < BOND_SLOTS; i++) any |= slot_valid(i);
        if (any && !S.pairing) {   // pairing is only accepted in the pairing window (DPI + LEFT, 3 s) or with no host stored
            LOG[0x2C]++;
            sd_ble_gap_sec_params_reply(ch, BLE_GAP_SEC_STATUS_PAIRING_NOT_SUPP, NULL, NULL);
            break;
        }
        memset(&S.keyset, 0, sizeof S.keyset); memset(&S.peer_id, 0, sizeof S.peer_id);
        S.keyset.keys_own.p_enc_key = &S.own_enc;
        S.keyset.keys_peer.p_enc_key = &S.peer_enc;
        S.keyset.keys_peer.p_id_key = &S.peer_id;
        logev(0x10000 | sd_ble_gap_sec_params_reply(ch, BLE_GAP_SEC_STATUS_SUCCESS, &secp, &S.keyset));
        break;
    }
    case BLE_GAP_EVT_AUTH_STATUS:
        if (ev->evt.gap_evt.params.auth_status.auth_status == BLE_GAP_SEC_STATUS_SUCCESS) {
            const uint8_t *ia = S.peer_id.id_addr_info.addr;
            S.id_ok = (ia[0] | ia[1] | ia[2] | ia[3] | ia[4] | ia[5]) ? 1 : 0;
            if (S.id_ok) S.id = S.peer_id;
            S.bonded = 1; slot_alloc(S.id_ok ? &S.id : NULL); S.target = S.slot; S.pairing = 0; S.nonce = S.new_nonce;
            bond_save();
        }
        logev(0x20000 | ev->evt.gap_evt.params.auth_status.auth_status);
        break;
    case BLE_GAP_EVT_SEC_INFO_REQUEST: {
        const ble_gap_evt_sec_info_request_t *r = &ev->evt.gap_evt.params.sec_info_request;
        int hit = -1;
        if (r->enc_info)
            for (int i = 0; i < BOND_SLOTS; i++) {
                const ble_gap_enc_key_t *k = (const ble_gap_enc_key_t *)(slot_rec(i) + 2);
                if (slot_valid(i) && r->master_id.ediv == k->master_id.ediv && memcmp(r->master_id.rand, k->master_id.rand, 8) == 0) hit = i;
            }
        if (hit >= 0) { slot_load(hit); S.target = (uint8_t)hit; S.reconn = 1; LOG[0x28] = (uint32_t)hit; sd_ble_gap_sec_info_reply(ch, &S.own_enc.enc_info, NULL, NULL); }
        else sd_ble_gap_sec_info_reply(ch, NULL, NULL, NULL);
        break;
    }
    case BLE_GAP_EVT_CONN_SEC_UPDATE:
        // link re-encrypted with the stored LTK: restore the peer's CCCD state so notifications flow without a new subscription
        if (S.reconn && S.sa_len) {
            LOG[0x24] = sd_ble_gatts_sys_attr_set(ch, S.sa, S.sa_len, BLE_GATTS_SYS_ATTR_FLAG_SYS_SRVCS | BLE_GATTS_SYS_ATTR_FLAG_USR_SRVCS);
            S.reconn = 0;
            S.notify_on = 1;           // the stored CCCD state was restored: notifications are on without a new subscription
            S.neutral_pending = 1;
        }
        if (LOG[0x31] != 6) request_fast_conn(ch);   // retry now that the link is encrypted / services are discovered
        break;
    case BLE_GAP_EVT_PHY_UPDATE_REQUEST: {
        ble_gap_phys_t p = {BLE_GAP_PHY_AUTO, BLE_GAP_PHY_AUTO};
        sd_ble_gap_phy_update(ch, &p);
        break;
    }
    case BLE_GAP_EVT_DATA_LENGTH_UPDATE_REQUEST:
        sd_ble_gap_data_length_update(ch, NULL, NULL);
        break;
    case BLE_GAP_EVT_CONN_PARAM_UPDATE_REQUEST:
        sd_ble_gap_conn_param_update(ch, &ev->evt.gap_evt.params.conn_param_update_request.conn_params);
        break;
    case BLE_GATTS_EVT_SYS_ATTR_MISSING:
        if (S.bonded && S.sa_len)
            sd_ble_gatts_sys_attr_set(ch, S.sa, S.sa_len, BLE_GATTS_SYS_ATTR_FLAG_SYS_SRVCS | BLE_GATTS_SYS_ATTR_FLAG_USR_SRVCS);
        else
            sd_ble_gatts_sys_attr_set(ch, NULL, 0, 0);
        break;
    case BLE_GATTS_EVT_EXCHANGE_MTU_REQUEST:
        sd_ble_gatts_exchange_mtu_reply(ch, BLE_GATT_ATT_MTU_DEFAULT);
        break;
    case BLE_GATTS_EVT_WRITE: {
        const ble_gatts_evt_write_t *w = &ev->evt.gatts_evt.params.write;
        if (w->handle == S.h_rep.cccd_handle && w->len >= 2) {
            S.notify_on = w->data[0] & 1;
            if (S.notify_on) S.neutral_pending = 1;   // host just (re)subscribed: start from a clean button state
            sa_capture_and_save(ch);
        }
        break;
    }
    case BLE_GAP_EVT_TIMEOUT:
    case BLE_GATTS_EVT_TIMEOUT:
        sd_ble_gap_disconnect(ch, BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
        break;
    default:
        break;
    }
}

void blehid_poll(void) {
    flash_step();
    for (int i = 0; i < 8; i++) {
        uint16_t len = sizeof S.evt_buf;
        if (sd_ble_evt_get((uint8_t *)S.evt_buf, &len) != NRF_SUCCESS) break;
        on_evt((const ble_evt_t *)S.evt_buf);
    }
}

// rep: buttons, dx16, dy16, wheel, pan (7 bytes). returns SD error / 0xFFFF if not ready
uint32_t blehid_send(const uint8_t *rep) {
    if (S.conn == BLE_CONN_HANDLE_INVALID) return 0xFFFF;
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

// Main-loop hook (replaces the call to the app report-flag builder 0x14AE4): run it, then service BLE events.
// Input handling is NOT reimplemented here: the stock firmware (sensor task, button scan + remap engine, polling timer,
// report builder 0x14CEC) produces the mouse report; BLE is just a third transport at the hand-off point where the
// builder calls the USB sender 0x15E5C (see blehid_tx_stock / MOUSE_T in mk_ble.py).
#define APP_BUILD ((void (*)(void))0x35AE5)
void blehid_tick(void) {
    APP_BUILD();
    chord_poll();
    pair_chord_poll();
    if (SD_FLAG) { host_chord_poll(); add_chord_poll(); pair_window_poll(); host_switch_apply(); }
    if (SD_FLAG && LOG[0x3C]) { uint32_t c = LOG[0x3C]; LOG[0x3C] = 0; if (c == 1) host_switch(1); else if (c == 2) host_switch(-1); else if (c == 3) pair_window_open(); }   // SWD test hook
    LOG[0x2D] = S.pairing | (uint32_t)S.target << 8 | (uint32_t)S.slot << 16 | (S.conn != BLE_CONN_HANDLE_INVALID) << 24;   // pairing window / selected host / active slot / connected
    led_tick();
    if (!SD_FLAG) return;          // DONGLE mode: SoftDevice off, nothing else to do
    blehid_poll();
    // USB took over (cable enumerated): release the buttons on the BLE host so nothing stays pressed there
    uint8_t usb = *(volatile uint8_t *)0x200035DE;
    if (usb && !S.usb_prev) S.neutral_pending = 1;
    S.usb_prev = usb;
    if (S.neutral_pending && S.conn != BLE_CONN_HANDLE_INVALID && S.notify_on && send_neutral() == 0) S.neutral_pending = 0;
    if (LOG[0x3A] && S.conn != BLE_CONN_HANDLE_INVALID) { LOG[0x3A] = 0; request_slow_conn(S.conn); S.slow = 1; }   // SWD test hook
    // power: idle link -> slow params with slave latency
    if (S.conn != BLE_CONN_HANDLE_INVALID && !S.slow && S.notify_on && ((RTC1_COUNTER - S.last_tx) & 0xFFFFFF) > 5 * 32768) {
        request_slow_conn(S.conn); S.slow = 1;
    }
    // power: the stock boot code starts the 32 MHz crystal directly (before the SD existed), so the SD does not own it and it
    // stays on forever. A request+release through the SD API makes the SD take it over; from then on it only runs for radio
    // events. Skipped while USB is up (USB needs the crystal; its driver requests/releases through the SD itself).
    if (usb || (*(volatile uint32_t *)0x40000438 & 1)) S.hf_released = 0;
    else if (!S.hf_released && ((RTC1_COUNTER - S.hf_t0) & 0xFFFFFF) > 3 * 32768) {
        LOG[0x36] = sd_clock_hfclk_request();
        LOG[0x37] = sd_clock_hfclk_release();
        // keep the stock driver's own request count consistent (it holds the boot-time request): otherwise a later USB attach
        // would count 1 -> 2 without ever asking the SD for the crystal, and USB would run on the inaccurate internal oscillator
        for (int i = 0; i < 4 && *(volatile uint32_t *)0x20007C08; i++) ((void (*)(void))0x309A1)();   // nrf_drv_clock_hfclk_release (orig 0xF9A0)
        LOG[0x35]++;
        S.hf_released = 1;
    }
    // battery: stock battery.c percentage (ADC average -> lookup table) @0x20003076, exposed through BAS
    uint8_t v = *(volatile uint8_t *)0x20003076;
    if (v > 100) v = 100;
    if (!v || v == S.bat) S.bat_cand = 0;
    else if (v != S.bat_cand) { S.bat_cand = v; S.bat_t0 = RTC1_COUNTER; }          // new candidate: start the stability timer
    else if (((RTC1_COUNTER - S.bat_t0) & 0xFFFFFF) > BAT_STABLE_TICKS) {             // stable for 30 s (the stock startup/charger transient is ignored)
        S.bat = v; S.bat_cand = 0; bat_keep(v);
        if (S.conn != BLE_CONN_HANDLE_INVALID) {
            uint16_t len = 1;
            ble_gatts_hvx_params_t hp;
            memset(&hp, 0, sizeof hp);
            hp.handle = S.h_bat.value_handle;
            hp.type = BLE_GATT_HVX_NOTIFICATION;
            hp.p_len = &len;
            hp.p_data = &S.bat;
            sd_ble_gatts_hvx(S.conn, &hp);   // ignored if the host did not subscribe; a read always returns S.bat
        }
    }
}

// Called from the patched stock idle->System OFF path (SD mode only): leave the host cleanly before the chip powers down.
void blehid_before_sleep(void) { LOG[0x40]++; LOG[0x41] = RTC1_COUNTER; leave_link(); LOG[0x42]++; }   // LOG[0x40..] survive the reset (not cleared at init)

// Stock mouse report (builder 0x14CEC -> buffer 0x200035E5): [0]=buttons [1]=wheel [2:3]=X [4:5]=Y [6]=pan.
// Returns 1 when the report was accepted by the SoftDevice (the stock code then clears its accumulators), else 0 (it keeps
// accumulating and retries on the next pass, which also rate-limits to what the connection can carry).
uint32_t blehid_tx_stock(const uint8_t *b) {
    if (!SD_FLAG) return 0;
    if (S.slow && S.conn != BLE_CONN_HANDLE_INVALID) { request_fast_conn(S.conn); S.slow = 0; }
    uint8_t r[7] = {b[0], b[2], b[3], b[4], b[5], b[1], b[6]};
    uint32_t e = blehid_send(r);
    LOG[0x20] = e;
    if (e == 0) { LOG[0x21]++; S.last_tx = RTC1_COUNTER; return 1; }
    return 0;
}

// exported entry table (first 16 bytes of the image)
__attribute__((section(".entry"), used)) const uint32_t ENTRY[8] = {
    (uint32_t)blehid_init, (uint32_t)blehid_tick, (uint32_t)blehid_send, (uint32_t)&S, (uint32_t)blehid_init_nosd, (uint32_t)&S.chord_p0,
    (uint32_t)blehid_tx_stock, (uint32_t)blehid_before_sleep};
