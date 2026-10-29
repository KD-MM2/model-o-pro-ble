# 13 — Open issues for the app image

Priority: **P1** affects daily use or trust in the numbers, **P2** worthwhile, **P3** nice to have.

| # | Pri | Item | Notes / how to close |
|---|---|---|---|
| 1 | P1 (skipped by owner) | Battery life never measured | Use a current meter (PPK2): idle connected, moving, advertising, System OFF. Compare with the stock dongle mode. Only then tune further. |
| 2 | P1 (skipped by owner) | 2.4 GHz dongle mode not re-tested after relocation | Switch with DPI+Back+Forward, check cursor/buttons/wheel via the dongle, switch back. Stock radio path is unmodified but unverified by us. |
| 3 | P1 (skipped by owner) | BLE tested on one Windows host only | Test Linux (BlueZ), macOS, Android: pairing, reconnect, 8 buttons, wheel/pan, battery, latency. |
| 4 | P2 | ~~Stock 1 kHz TIMER1 tick keeps HFINT on when idle~~ **dropped by owner (2026-10-29): too risky** | Not done on purpose. The stock sleep logic depends on this tick (idle counter 0x20003048, handler orig 0x18BA4), so stopping it can break idle detection, the 7-minute sleep or wake-up, with a failure that only shows after minutes of idling. If it is ever revisited: measure with a current meter first (#1) to see whether it is worth it, and test under `faultcatch.py` with a full idle → System OFF → wake cycle. |
| 5 | P2 | ~~LED PWM runs with LED off~~ **tried and reverted (2026-10-29)** | A gate that stopped PWM0 while the status LED was dark (`led_pwm_gate`) broke the **DPI LED**: the stock firmware drives both LEDs from PWM0's loops-done interrupt (handler orig 0x66F0 → nrfx PWM IRQ handler 0xD790 → LED update callback at 0x6690, which copies duty values for both LED buffers); PWM1 (DPI LED) has no interrupt and just free-runs. Stopping PWM0 stalled the stock LED engine, so the DPI LED stopped reacting (found by the owner: it no longer lit on lift). It also saved nothing: PWM1 stays enabled and keeps the 16 MHz clock requested. Not worth redoing without owning the whole stock LED engine; [07 §13](07-internals.md#13-the-stock-led-engine). |
| 6 | P2 | ~~Idle sleep fixed at stock 420 s~~ **done** | CORE has no sleep setting for this mouse (checked). Now a build-time constant `BLE_SLEEP_S` in `blehid.c` written to u16 @0x200038CB at init (verified: 60 → RAM `0x3c`, back to 420). |
| 7 | P2 | ~~Only one bond stored~~ **done** | 4 host slots, DPI + Forward/Back to switch, DPI + Left to add, a separate advertising address per host (no whitelist/directed advertising needed); [07 §12](07-internals.md#12-multiple-hosts-item-7-2026-10-29). Verified with two real hosts (Windows PC + phone): ~2 s switches, re-pairing the same host keeps its slot. Not verified: pairing refusal outside the window, a third/fourth real host, Linux/macOS hosts. |
| 8 | P2 (done 2026-10-27, see 14) | Rare stock paths unverified | ~380 unpatched in-old-range words; CLI, 2.4G link internals, stock firmware-update path (bootloader gone). Smoke-test each; suspect an unrelocated pointer first. |
| 9 | P2 | `--include-sd` NVMC flashing path only dry-run | Verify on a spare/disposable state or a CMSIS-DAP probe; until then document pyocd as the proven first-install route. |
| 10 | P2 | Rig scripts edited, not re-run | `rig/windows/*` and `winctl.sh` were parametrised after the last live run; re-run pair/cursor/battery/btnwatch. |
| 11 | P3 | Adv switch 30 s → 500 ms and BAS notify cadence not timed | Capture with a sniffer or btmon. |
| 18 | P2 (done 2026-10-27) | Windows showed battery 50 % while the mouse held 100 % | Root cause: the stock percentage restarts at 100 on boot/charger change and decays for ~25 s; I had read the startup value and Windows had cached a mid-decay value. Fix in `blehid.c`: publish only after 30 s stable, keep the last published level in RAM (`0x2003F0E0`) across soft resets. Residual: stock accuracy ±~7 points (36 % vs 43 % on consecutive boots). |
| 12 | P3 | `LOG[0x40..0x42]` garbage after a cold power-up | Not cleared on purpose (survive reset); add a magic/valid word. |
| 13 | P3 | Battery % noisy for first seconds | Already filtered (3 s stability); could seed from a stored last value. |
| 14 | P3 | Legacy Just Works pairing | LESC / passkey option. |
| 15 | P3 | Factory-unit APPROTECT state unknown | Document what a locked unit requires (ERASEALL loses the vendor bootloader). |
| 16 | P3 | BLE settings not reachable from Glorious CORE | Needs new vendor HID commands (shares work with [12](12-usb-update-plan.md)). |
| 17 | P3 | Two-step test of USB↔BLE hand-over edge cases | Plug/unplug during motion, with a button held, during a mode switch. |
| 20 | P2 | Exact battery threshold tables never read out | They are built in RAM at init (coarse 11 × u16 @0x2000308C, fine 111 × u16 @0x200030A2); the percent algorithm is decoded in [07](07-internals.md) but the values need one live read: `tools/probe.py mem 0x2000308C 256` + `mem 0x20003074 16`. The flash curve at 0x3DA44..0x3DB46 (codes 606..783 ≈ 3.2→4.1 V) matches the table sizes but has no found xref — verify against the RAM dump before believing it. |
| 19 | P2 (owner hardware change) | 350 mAh → 650 mAh battery swap | The voltage→percent map is capacity-independent; change nothing unless the new pack is not a standard 4.2 V LiPo (a 4.35 V HV cell breaks the 100 % end, a 3.5 V-min cell gets over-discharged at the 3.2 V 0 % end). Verify charging terminates normally and % tracks a measured pack voltage after the swap. |

Stability checklist before calling the image "release": items 1–3 done, #8 smoke-tested, a final
tagged backup and `build/…_ble.hex` hash recorded in the README.
