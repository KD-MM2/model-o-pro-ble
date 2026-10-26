# 13 — Open issues for the app image

Priority: **P1** affects daily use or trust in the numbers, **P2** worthwhile, **P3** nice to have.

| # | Pri | Item | Notes / how to close |
|---|---|---|---|
| 1 | P1 (skipped by owner) | Battery life never measured | Use a current meter (PPK2): idle connected, moving, advertising, System OFF. Compare with the stock dongle mode. Only then tune further. |
| 2 | P1 (skipped by owner) | 2.4 GHz dongle mode not re-tested after relocation | Switch with DPI+Back+Forward, check cursor/buttons/wheel via the dongle, switch back. Stock radio path is unmodified but unverified by us. |
| 3 | P1 (skipped by owner) | BLE tested on one Windows host only | Test Linux (BlueZ), macOS, Android: pairing, reconnect, 8 buttons, wheel/pan, battery, latency. |
| 4 | P2 | Stock 1 kHz TIMER1 tick keeps HFINT on when idle | Gate carefully; stock sleep depends on it (idle counter 0x20003048, handler orig 0x18BA4). |
| 5 | P2 | LED PWM runs with LED off | Stop PWM0 when dark. |
| 6 | P2 | Idle sleep fixed at stock 420 s | Expose as setting (u16 @0x200038CB) via CORE or a BLE/vendor command. |
| 7 | P2 | Only one bond stored | Multi-host slots (like the O3's 3 channels): N bond records + chord to select + directed advertising. |
| 8 | P2 | Rare stock paths unverified | ~380 unpatched in-old-range words; CLI, 2.4G link internals, stock firmware-update path (bootloader gone). Smoke-test each; suspect an unrelocated pointer first. |
| 9 | P2 | `--include-sd` NVMC flashing path only dry-run | Verify on a spare/disposable state or a CMSIS-DAP probe; until then document pyocd as the proven first-install route. |
| 10 | P2 | Rig scripts edited, not re-run | `rig/windows/*` and `winctl.sh` were parametrised after the last live run; re-run pair/cursor/battery/btnwatch. |
| 11 | P3 | Adv switch 30 s → 500 ms and BAS notify cadence not timed | Capture with a sniffer or btmon. |
| 18 | P2 | Windows showed battery 50 % while the mouse held 100 % | Seen 2026-10-26 after a reflash: Windows property = 50 (last update 20:43:29), `S.bat` = 100, stock byte = 100. A transient value was probably published after boot and Windows did not refresh. Fix idea: publish only after ~30 s uptime and require a longer stability window; check whether Windows subscribes to the BAS CCCD. |
| 12 | P3 | `LOG[0x40..0x42]` garbage after a cold power-up | Not cleared on purpose (survive reset); add a magic/valid word. |
| 13 | P3 | Battery % noisy for first seconds | Already filtered (3 s stability); could seed from a stored last value. |
| 14 | P3 | Legacy Just Works pairing | LESC / passkey option. |
| 15 | P3 | Factory-unit APPROTECT state unknown | Document what a locked unit requires (ERASEALL loses the vendor bootloader). |
| 16 | P3 | BLE settings not reachable from Glorious CORE | Needs new vendor HID commands (shares work with [12](12-usb-update-plan.md)). |
| 17 | P3 | Two-step test of USB↔BLE hand-over edge cases | Plug/unplug during motion, with a button held, during a mode switch. |
| 18 | P2 | Exact battery threshold tables never read out | They are built in RAM at init (coarse 11 × u16 @0x2000308C, fine 111 × u16 @0x200030A2); the percent algorithm is decoded in [07](07-internals.md) but the values need one live read: `tools/probe.py mem 0x2000308C 256` + `mem 0x20003074 16`. The flash curve at 0x3DA44..0x3DB46 (codes 606..783 ≈ 3.2→4.1 V) matches the table sizes but has no found xref — verify against the RAM dump before believing it. |
| 19 | P2 (owner hardware change) | 350 mAh → 650 mAh battery swap | The voltage→percent map is capacity-independent; change nothing unless the new pack is not a standard 4.2 V LiPo (a 4.35 V HV cell breaks the 100 % end, a 3.5 V-min cell gets over-discharged at the 3.2 V 0 % end). Verify charging terminates normally and % tracks a measured pack voltage after the swap. |

Stability checklist before calling the image "release": items 1–3 done, #8 smoke-tested, a final
tagged backup and `build/…_ble.hex` hash recorded in the README.
