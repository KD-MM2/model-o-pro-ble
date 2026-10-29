# 11 — History, honest status, and next steps

## Timeline (condensed)

| Stage | Result |
|---|---|
| 0. Starting point | Mouse ran the stock vendor app only (2.4 GHz dongle + USB), via two hand-made boot stubs (16 B at 0x0, stub at 0x1000), no MBR/SoftDevice/bootloader. SWD open. |
| 1. Study | App is a SoftDevice-first SDK build whose 39 SVC numbers match S140 7.x; BLE code dormant (`[0x20003830]==0`); never calls `sd_ble_enable`/`cfg_set`. |
| 2. Relocation | MBR + S140 7.3.0 + the app rebased 0x6000 → 0x27000 (`relocate.py`); boots, enumerates over USB, CFSR 0. Report: [appendix/report-s140-bringup.md](appendix/report-s140-bringup.md). |
| 3. SD bring-up + advertising | Stub enables the SD from the app boot path, registers HID/BAS/DIS, advertises; Windows pairs. |
| 4. Own input code (wrong turn) | Re-implemented motion/buttons → jerky, wrong behaviour. Reverted. **Rule: do not reinvent.** |
| 5. Stock pipeline hook | `MOUSE_T` at the stock transport call forwards the builder's report; motion/buttons/wheel perfect; ~72 reports/s. |
| 6. Fixes | DPI-click reboot (SD flash API for the stock erase/write); latency (7.5 ms connection interval requested). |
| 7. Modes | BLE ⇄ dongle by chord; USB priority; force re-pair; LED feedback; battery service. |
| 8. Power | HFXO takeover, idle slave latency, slow advertising, SD-safe System OFF (see [06 §6](06-user-guide.md#6-power-behaviour)). |

Raw notes of the whole run: [appendix/worklog-raw.md](appendix/worklog-raw.md).

## Verified vs. not verified (read before trusting)

Verified on hardware (details in README table): USB mode, BLE motion/buttons/wheel/pan, bonding
across resets/reflash, battery %, mode switch round trip, re-pair, USB priority, LED patterns,
HFXO state, idle parameters accepted by Windows, System OFF + wake.

**Not verified:**

* Real **current consumption** — no meter. All power claims are from register/clock state.
* **2.4 GHz dongle** operation after relocation (the stock radio code path is unmodified and the
  user reported it fine; it was not retested by us). Dongle-mode LED (green) and the chord return
  path were exercised.
* **Linux/macOS/Android** as BLE hosts. Only Windows (build not recorded).
* Rare stock paths: the vendor **CLI**, **firmware-update** path (the original USB bootloader is
  gone), anything touching the ~380 unpatched old-range words.
* The `--include-sd` NVMC flashing path was only dry-run here (the SD itself was flashed with
  pyocd + CMSIS-DAP during bring-up).
* Advertising timing switch (30 s → 500 ms) and BAS notify cadence were not timed explicitly.
* Multi-host (4 slots): verified with two real hosts; a third/fourth host, Linux/macOS hosts and the refusal of pairing outside the window were not exercised.

## Ideas not done

1. ~~Stop the stock 1 kHz TIMER1 tick when idle.~~ **Dropped by the owner as too risky** ([13 #4](13-open-issues.md)): it keeps HFINT running
   whenever awake, but the stock sleep logic depends on it (idle counter at 0x20003048, TIMER1 handler at orig 0x18BA4).
2. ~~LED PWM: stop it when dark~~ tried and **reverted**: PWM0's interrupt is the stock LED engine's heartbeat for both LEDs, stopping it froze the DPI LED ([13 #5](13-open-issues.md)).
3. **Shorter idle sleep**: the stock threshold is 420 s (u16 @ 0x200038CB); expose as a BLE
   setting or patch the default.
4. ~~Multiple bonds / host slots~~ done (item 7): [07 §12](07-internals.md#12-multiple-hosts-item-7-2026-10-29).
5. **Measure** with a current meter (e.g. PPK2) and tune connection intervals/latency
   (`probe.py slowconn …` lets you A/B without reflashing).
6. **LESC / passkey** pairing instead of legacy Just Works.
7. **DFU over BLE** — would need a bootloader, and the original is gone.
8. **Port to other nRF52840 Glorious mice** (Model O3/D3 share the MCU): hook addresses and
   pins differ; the method (relocate → SD → stock-report hook) is the same. The O3 firmware
   (`mouse_black.bin`, 164 840 B) is a good behavioural reference.

## Adapting to another firmware version

1. Dump + extract the new app; compare `sha256`.
2. `python tools/rebase_scan.py <app.bin> > tools/scan.txt` and re-curate the filters in
   `relocate.py` (look for false positives/negatives; test on hardware with the SD present).
3. Re-find each hook: transport call (`bl <usb send>` inside the mouse report builder),
   `bl` in the init path before the main loop, end-of-main-loop `bl`, the direct DCDC write,
   the vendor-radio-init compare, flash erase/write `bne`s, the idle→SYSTEMOFF compare,
   radio-teardown `bl`s (`mk_ble.py`'s `PATCHES` list asserts each expected byte string).
4. Re-derive the stock addresses hard-coded in `blehid.c` (`APP_BUILD` 0x35AE5, HFCLK release
   0x309A1, RAM variables) — all are `orig + 0x21000`.
