# 07 — Internals (reference)

Address convention: **"orig"** = address in the stock image (base 0x6000). **"reloc"** = orig
+ **D = 0x21000** (the image running at 0x27000). `tools/fdis.py` uses orig addresses.

## 1. Flash and RAM map

| Flash | Content | Written by |
|---|---|---|
| 0x00000–0x00AFF | Nordic MBR | S140 hex |
| 0x01000–0x26497 | SoftDevice S140 7.3.0 | S140 hex (never modified) |
| 0x27000–0x3E206 | stock app, relocated | `relocate.py` + `mk_ble.py` patches |
| 0x3F000–0x3F109 | STUB (SD bring-up, mode select) | `mk_ble.py` (Keystone) |
| 0x3F800 | THUNK (main-loop poll) | " |
| 0x3F840 | DCDC_T (DC/DC enable, SD-safe) | " |
| 0x3F880 | GATE_T (skip vendor radio init when SD on) | " |
| 0x3F8C0 | MOUSE_T (transport: USB else BLE) | " |
| 0x3F900 | SYSOFF_T (System OFF via SD) | " |
| 0x3F940 / 0x3F960 | RADIO_A_T / RADIO_B_T (radio-teardown gates) | " |
| 0x3F980 / 0x3F9A0 / 0x3F9C0 | RADIO_C_T / RADIO_D_T / RADIO_E_T (radio/timer start gates: 0x15A1C, 0x18AD0, 0x16740) | " |
| 0x40000–0x412A3 | blehid blob (ENTRY table + code + rodata) | `fw/blehid` |
| 0x8B000, 0x8C000 | vendor settings pages | stock firmware, **preserved** |
| 0xFD000 | bond record (magic `B0DD0001`, 64 B) | blehid |
| 0xFE000 | mode record `{C0DE0001, mode, ~mode, generation}` | blehid |

| RAM | Content |
|---|---|
| 0x20000000–0x20002FFF | SoftDevice |
| 0x20003000– | stock app data (`.data/.bss`); app RAM starts ~0x20003000 |
| 0x20003003 | vendor mode var (1) |
| 0x2000300C | stock flags, bit2 = "mouse report due" |
| 0x20003016 / 0x20003018 | motion accumulators X / Y |
| 0x20003048 | stock idle counter (+1/s); threshold u16 @0x200038CB (420 s) |
| 0x20003076 | stock battery percent |
| 0x20003270 | LED duty buffer (R,G,B u16) |
| 0x200035DE | stock "direct USB" flag |
| 0x200035E5 | stock mouse report buffer (7 bytes used) |
| 0x20003704 | `app_scheduler` struct (the stub initialises it; the SD event queue needs it) |
| 0x20003830 | `nrf_sdh` "SD enabled" flag (0 = no SD, 1 = SD) |
| 0x20007C08 | stock `nrf_drv_clock` HFCLK request count |
| 0x2000B000–0x2000B1FF | app_sched queue buffers (header/data) |
| 0x2000B400–0x2000D3FF | blehid state `S` and bss (`ENTRY[3]` = `&S`) |
| 0x2003F000–0x2003F03F | **stub log** (see §6) |
| 0x2003F0E0–0x2003F0EB | battery hand-off record: magic `BA770001`, last published level, `~level` (survives soft resets) |
| 0x2003F100– | **blehid log** `LOG[]` (see §6) |

## 2. Relocation

Shift D = +0x21000 for a flat Thumb-2 image with no source or relocation records.

* **PC-relative** encodings (B, BL, B.W, CBZ/CBNZ, ADR, `LDR rX,[pc,#]`) move with the image
  → untouched.
* **Absolute words** must each get +D: vector-table entries, literal-pool pointers
  (consumed by `LDR rX,[PC,#imm]`), data-table pointers, and flash pointers inside the
  *RAM-initialisation blob* at orig 0x1C944–0x1CC8F (IAR packbits-style; `unpack.py` decodes,
  `relocate.py` patches and re-packs it literal-only at the same place).
* Words that merely look like addresses must *not* be patched: string tails (`"%s\0\0"`),
  `pop {…,pc}` + padding halfwords, constants like the CRC poly 0x11021, key tables 0x8200–0x8403,
  the bss length 0x76A8.

`rebase_scan.py` produces candidates (`scan.txt`: must-change pool/vector words + ~700
"ambiguous"); `relocate.py` applies a hand-curated filter (documented inline) and a second
pass for pools the scanner mis-decoded as code (~20 extras: e.g. the pool at 0x64CC/0x64D0 =
INIT-table bounds). Result: 584 words patched, 210 deliberately excluded, written to
`build/golden_app_27000.bin.json` (list of exclusions with reasons).

Caveat: ~380 in-old-range words remain unpatched (instruction pairs, strings, constants). The
common paths (boot, USB, motion, buttons, BLE, DPI, sleep) were exercised on hardware;
**rarely used paths (CLI, 2.4 GHz link) were not**. If something faults there, suspect an
unrelocated pointer first.

A "stub-only" build (SoftDevice absent but old 0x6000 area still holding S140 bytes) *hides*
stale old-address pointers; test relocations with the SoftDevice present and the old region
erased, or at least on the real SD build.

## 3. Boot sequence in BLE mode

```
reset → MBR → SoftDevice stub → app reset vector (reloc 0x27000+…) → stock init
   … code at orig 0xE878 (the `bl 0x6F68` of the USB/app init) is hooked → STUB:
   1. read 0xFE000: valid record with mode 2 (DONGLE)? → call blob.ENTRY[4] (init_nosd: LED+chord) and continue stock path
   2. otherwise (BLE):
      clear stub LOG; init app_scheduler struct @0x20003704 (queue @0x2000B000/B100, 16 events)
      nrf_drv_power_init                (stock fn, orig 0xFB0C)
      nrf_sdh_enable_request            (stock fn, orig 0x11C18)       → sets [0x20003830]=1
      sd_ble_cfg_set(GATTS attr table size = 720)   svc 0x69, cfg id 0xA1
      sd_ble_cfg_set(vendor-specific UUID count = 0)
      sd_ble_enable(app_ram_base=0x20003000)        svc 0x60
      blob.ENTRY[0] = blehid_init       (GAP name/appearance/PPCP, DIS/BAS/HID, advertising)
   3. tail-call the original 0x6F68
main loop end (orig 0xE92C `bl 0x14AE4` hooked → THUNK): blehid_tick
```

`blehid_tick` runs the app's report-flag builder (orig `0x14AE4`) first, then chord/LED
handling, then (SD on) the BLE event pump `blehid_poll` (`sd_ble_evt_get` loop), the USB-edge
neutral report, idle-slow connection parameters, the HFXO takeover and battery publishing.

SD events are *polled* from the main loop (not interrupt driven via the app_sched path).

## 4. Patch table

All sites are asserted (`mk_ble.py` compares the original bytes before writing).

| Orig addr | Original | Patched to | Why |
|---|---|---|---|
| 0xE878 | `bl 0x6F68` | `bl STUB` | SD bring-up hook |
| 0xE92C | `bl 0x14AE4` | `bl THUNK` | main-loop hook |
| 0x6F94 | `ldr/str` DCDCEN direct write (`07490860`) | `bl DCDC_T` | POWER is SD-owned: `svc 0x3f sd_power_dcdc_mode_set` when SD on, else the direct write |
| 0xE888 | `cmp r0,#1; bne` | `bl GATE_T` | skip the vendor 2.4 GHz radio init when SD is on (SD owns RADIO) |
| 0x14DC8 | `bl 0x15E5C` (USB send) | `bl MOUSE_T` | transport: try USB (returns 1) else `ENTRY[6]` |
| 0xABA0 | `cmp r0,#1; beq` (`012804d0`) | `bl SYSOFF_T` | idle → System OFF through `sd_power_system_off` (svc 0x33), leaving the link first |
| 0xABDA, 0xABDE | `bl 0x15B70`, `bl 0x18B24` | `bl RADIO_A_T/B_T` | sleep prep tears down the 2.4G radio with direct NVIC/RADIO writes → APP_MEMACC fault with SD on; run only when SD off |
| 0x19B84 | `bl 0x15A1C` (2.4G radio power-up) | `bl RADIO_C_T` | link state machine (module handler orig 0x19ACC, table entry 0x1A930): on USB **removal** it sets the vendor mode var to 1 (BLE transport needs that) and then powers the radio up → APP_MEMACC. Keep the state write, skip the radio call |
| 0x19B8C | `b.w 0x18AD0` (2.4G TIMER0 setup) | `b.w RADIO_D_T` | same case, tail call; TIMER0 is SD-owned |
| 0x19B0E | `b.w 0x15B70` (radio teardown) | `b.w RADIO_A_T` | same state machine, other event |
| 0x14880 | `bl 0x16740` (radio start) | `bl RADIO_E_T` | vendor command 0xA0 (wireless parameters) handler, reachable from CORE |
| 0xBE88 | `bne` (`13d1`) | `nop` | stock flash **erase** takes the direct-NVMC path unless mode==2; force the SD flash API (`sd_flash_page_erase`, svc 0x28) |
| 0xBEEE | `bne` (`14d1`) | `nop` | same for flash **write** (`sd_flash_write`, svc 0x29) — this fixed "DPI click reboots" |

### The thunks (assembly generated in `mk_ble.py`)

* **MOUSE_T** — `bl USB_SEND(0x15E5C+D)`; if it returned 1 (USB accepted) done; else load
  `BLOB[24]` (= `ENTRY[6]`) and call it with the same report pointer.
* **SYSOFF_T** — if `[0x20003830]==0` jump to the original direct SYSTEMOFF path (orig
  0xABAE); else call `ENTRY[7]` (`blehid_before_sleep`: neutral report, 20 ms, disconnect, 30 ms)
  and return into the stock code, which then falls through to `svc 0x33`.
* **RADIO_x_T / GATE_T / DCDC_T** — `if SD_FLAG {skip/alternative} else {jump to the original}`.

### Why POWER/NVMC/RADIO accesses fault

With the SoftDevice enabled, application writes to peripherals it owns (POWER, NVMC, RADIO
and the radio-related NVIC lines) were observed to raise a SoftDevice fault, error id `0x1001`
(APP_MEMACC), which reaches the app's fault handler (orig 0x7474 → `bkpt`/reset). Always go through the SVC API (sd_flash_*, sd_power_*,
sd_clock_*). SVCs used here: 0x60 ble_enable, 0x61 evt_get, 0x69 cfg_set, 0x3F dcdc_mode_set,
0x33 system_off, 0x28/0x29 flash page erase/write, 0x42/0x43/0x44 hfclk request/release/is_running.

## 5. The report pipeline hook, precisely

```
builder (orig 0x14CEC), when [0x2000300C] bit2:
    r = stock report buffer 0x200035E5   {btn, wheel, Xlo, Xhi, Ylo, Yhi, pan}
    if [0x200035DE]==1 → direct USB IN (0x84BA)
    else switch [0x20003003]: 1 → 0x15E5C(report, 1, 8, 0)   [PATCHED: MOUSE_T]  (call site 0x14DC8)
                              2 → 0x9084(0,buf,8)           [2.4G radio]
    on success (r0==1): clear accumulators 0x20003016/18, clear bit2
```

`blehid_tx_stock(b)`: if SD off → 0; if the link is in slow/idle parameters, request fast
ones; build `{b0, b2, b3, b4, b5, b1, b6}` = `{buttons, Xlo, Xhi, Ylo, Yhi, wheel, pan}`;
`sd_ble_gatts_hvx` on the Report characteristic; return 1 only if the SD accepted it (error 0),
so the stock code clears the accumulators; otherwise they keep accumulating and are retried
the next pass (automatic rate-limiting to what the connection carries; nothing is lost).

## 6. Logs in RAM (read with `make status` / `probe.py mem`)

Stub log, base **0x2003F000** (written by `mk_ble.py`'s stub; word offsets):

| +0x00 | magic `B1E00001` (BLE path) / ending `B1E0FFFF` at +0x24 when the stub finished |
| +0x04 | `nrf_drv_power_init` return |
| +0x08 | `nrf_sdh_enable_request` return (0 = ok) |
| +0x0C | `sd_ble_cfg_set` (attr table) return |
| +0x10 | `sd_ble_cfg_set` (vs uuids) return |
| +0x14 | `sd_ble_enable` return |
| +0x18 | required app RAM end (SD writes it back) |
| +0x1C | `blehid_init` return |

blehid log `LOG[]` base **0x2003F100** (`uint32_t` indices, byte offset = index × 4):

| Index | Meaning |
|---|---|
| 0 | magic `B1E0A001` (init) / `A002` (nosd) |
| 1 | init stage; `0x1000` = all OK; `0x100|n` = failing step n; `0x2000|k` = STOP_AT |
| 2, 3..18 | event count, ring of last 16 BLE event ids |
| 0x20, 0x21 | last hvx result, reports sent |
| 0x22 | flash state; 0x23 = bonded; 0x24 sys_attr_set result; 0x25 next mode; 0x26 new generation; 0x27 addr_set result |
| 0x30 / 0x31 / 0x32 | conn interval at connect / after update (1.25 ms units) / slave latency |
| 0x33 / 0x34 | `conn_param_update` return (fast / slow) |
| 0x35 | HFXO takeovers; 0x36 / 0x37 returns of hfclk request / release |
| 0x38 0x39 0x3B 0x3A | **live-tuning**: interval, latency, supervision timeout, trigger (see 08) |
| 0x40 / 0x41 / 0x42 | before_sleep entered / RTC at entry / completed (**survive reset**; not cleared at init, so garbage after a cold power-up) |

## 7. BLE/GATT layout

| Item | Value |
|---|---|
| Name | "Model O PRO Wireless" |
| Appearance | 0x03C2 (Mouse) |
| Advertising | connectable scannable undirected; flags + appearance + HID UUID in adv data, name in scan response; 50 ms ×30 s then 500 ms |
| Services | DIS (PnP ID with VID 0x258A, PID 0x2015), BAS (0x2A19, read+notify), HID (0x1812) |
| HID | HID Information, **Report Map** (mouse, Report ID 1, 8 buttons, X/Y int16, wheel int8, AC Pan int8), Control Point, Protocol Mode, Report (input, notify) + Report Reference |
| Security | SMP LE legacy, Just Works, bonding; keys stored in page 0xFD000, restored on reconnect via `sd_ble_gatts_sys_attr_set` |
| Connection | preferred 7.5 ms/lat 0 (host usually ignores PPCP: the mouse sends an explicit update request); idle 15 ms/lat 20 |
| Address | random static, derived from the pairing generation (`sd_ble_gap_addr_set` when generation ≠ 0) |

## 8. Pin and peripheral reference

| Function | Pin / peripheral |
|---|---|
| LEFT / RIGHT / MIDDLE | P1.15 / P1.13 / P1.10 (active low) |
| BACK / FORWARD | P0.9 / P0.10 |
| DPI | P1.0 |
| Wheel A / B | P0.2 / P0.29 |
| Sensor SPI2 | SCK P0.12, MOSI P0.8, MISO P0.11, motion IRQ P0.6 |
| RGB LED | PWM0: P0.13 R, P0.15 G, P0.17 B |
| Button inputs read by chords | P0 IN `0x50000510`, P1 IN `0x50000810` |
| Timebase | RTC1 COUNTER `0x40011504`, 32 768 Hz (stock app timer) |
| 1 ms tick | TIMER1 (handler orig 0x18BA4, byte counter @0x2000306C) |

## 9. Stock functions reused (orig addresses)

| Function | Addr | Used for |
|---|---|---|
| nrf_drv_power_init | 0xFB0C | SD bring-up |
| nrf_sdh_enable_request | 0x11C18 | SD enable |
| nrf_drv_clock_hfclk_request / release / init | 0xF9D8 / 0xF9A0 / 0xFA34 | keeping the HFCLK refcount consistent |
| report builder | 0x14CEC | all mouse reports |
| flag builder | 0x14AE4 | called by `blehid_tick` first |
| button scan / macro engine | 0x16B0C / 0xE32C | buttons, remaps, macros |
| motion task | 0x1319C | motion accumulation |
| battery | 0xE088 | percent @0x20003076 |
| idle timer callback / sleep path | 0xAB44 / 0xAB98 → 0xABC4 | 420 s idle → System OFF |
| app fault handler | 0x7474 | `bkpt` on SD faults |

### 9.1 Battery voltage → percent map (decoded)

Struct @`0x20003074`: `+0x00` raw %, `+0x02` published % (BAS reads this), `+0x01` `p*2.5625`,
`+0x06` init flag, `+0x07` rise flag, `+0x08` zero flag, `+0x0A` last raw ADC, `+0x0C` 16-sample
average, `+0x10/+0x14` stabilization timer.

`0xE088` (per pass): 16-sample SAADC burst (`0xC870`), average → `+0x0C`; then a two-stage
threshold lookup against **two u16 tables built in RAM at init**: deciles (0,10,…100 %) at
`0x2000308C` (11 entries) and per-percent thresholds at `0x200030A2` (111 entries).
`avg < t[0]` → 0 %; `avg ≥ t[10]` → 100 %; else `percent = 10i + j` for the matched window.
`0xE2C0` smooths raw → published (the 3 s stability filter used by BAS).

The RAM values have never been dumped ([13 #18](13-open-issues.md)). Candidate flash source
`0x3DA44..0x3DB46`: 60 + 51 ascending u16 (codes 606..783, ≈ 3.2→4.1 V [INFERENCE]) + 11 decile
values — sizes match the tables exactly, but no code xref was found; treat as unverified.

## 10. Things the stock code has that this product does not use

Mode-2 paths (SD flash API when mode var == 2, the 0x9084 radio sender, svc 0x33) exist in the
vendor image because it is a generic SDK build; the product never ran with a SoftDevice. We use
them exactly because they are the vendor's own SD-aware branches.

## 11. Where the SoftDevice-hostile stock code lives (census, 2026-10-27)

40 stock functions load addresses of SD-owned peripherals (RADIO 0x40001000, TIMER0 0x40008000, RTC0, POWER/CLOCK, NVMC, NVIC). The 2.4 GHz link is a large cluster (orig 0x6c00–0x73cc, 0x9548, 0xac8c, 0xb220, 0x15a1c–0x16740, 0x17ae0, 0x1883c–0x18b24). In BLE mode it is never started (GATE_T skips the boot init), and most entry points are protected by the "radio is up" flag at `[0x2000361C+5]`, which stays 0. The unprotected *start* paths found so far are the four gated above. Method that found them: `tools/faultcatch.py` (see [08 §10](08-debugging.md#10-catching-a-real-fault-faultcatchpy)). If a new APP_MEMACC shows up, repeat it, then gate the call site the same way (`radio_gate()` in `mk_ble.py`).
