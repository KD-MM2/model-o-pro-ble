# 10 — Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pyocd`: `STLink error (29): Bad AP` | ST-Link V2 clone + `-t nrf52840` | use this repo's tools (generic `cortex_m` target) or a CMSIS-DAP probe |
| `pyocd`/tools cannot connect, "No ACK" | wiring, no series resistors, mouse unpowered, probe busy | check TP17/TP9/GND, power mouse from its own USB, `-f 100k`, make sure no other tool holds the probe |
| `make stock` → "does not look like the stock app" | the dump is from a chip that already runs the SoftDevice | use a dump taken before the first install, or reuse your existing `stock/golden_app.bin` |
| `mk_ble.py` → `AssertionError: (0x…, …)` | the stock app differs from v1.00.00 (hook bytes don't match) | check `sha256sum stock/golden_app.bin` = `18f8b30a…`; other versions need re-derived hook addresses and `scan.txt` |
| `fw/blehid/build.sh`: `llvm-objcopy: not found` | llvm not installed | `sudo apt install llvm` or `OBJCOPY=/path/to/llvm-objcopy` |
| Build prints `cannot find entry symbol _start` | harmless (freestanding blob, no entry) | ignore |
| After flashing: nothing happens, no LED, USB absent | flat battery, or bad image | charge/plug USB; `make status`; restore the known-good hex |
| LED shows only **green** blinks | the mode record says DONGLE | hold DPI+Back+Forward 3 s, or `tools/erase_page.py config --go` |
| 2 purple blinks every boot | no bond (pairing mode) | pair; if you already paired, the bond page was erased/never written — check `make status` bond magic |
| Windows: "Connected" but no cursor | stale bond with keys the mouse no longer has | remove device, `winctl.sh clean`, pair again; or force re-pair on the mouse |
| Cursor moves on the wrong computer | USB cable is plugged into another PC (USB has priority) | unplug it, or intended |
| DPI click reboots the mouse | an old build without the 0xBE88/0xBEEE flash patches | rebuild from this repo (the patches are in `mk_ble.py`) |
| Mouse resets by itself after 7 minutes idle | an old build without the SD-safe sleep path (`SYSOFF_T`, `RADIO_A/B_T`) | rebuild |
| Crystal always on, battery drains | an old build without the HFXO takeover; or USB attached | rebuild; `make status` should show `HFXO off` on battery |
| Crash / `bkpt @0x284d4` while debugging | you halted the CPU (SoftDevice assert) | detach, reset, never halt a running SoftDevice (08 rule 1) |
| `bkpt`/reset right after boot, CFSR 0 | SD fault 0x1001: some code writes POWER/NVMC/RADIO directly | find the offending stock site (orig address in the SD error info), gate it like the other thunks |
| Battery % jumps at boot | stock ADC average needs a few seconds | the module publishes only after 3 s of stability |
| Mouse stuck "dead" in System OFF with probe attached | emulated System OFF under a debugger | detach the probe, press a button |
| `hvx` returns `0x3401` | CCCD/sys attributes not set yet | normal before the host enables notifications |
| BLE events show `0x10,0x23,0x24,0x14,0x11` repeating | host retries encryption with an old key | remove host-side bond |
| Chords do nothing | wrong pins on your board or masks overridden by SWD | `probe.py chord …`; check pin table in 07 |
| Sleep looks "not working" | debugger attached (emulated), or the idle timer is long | detach; the stock idle sleep is 420 s |

## Hard-won lessons (short form)

* **Reuse the stock pipeline; do not reimplement input.** The first custom motion/button code
  made the cursor stutter and buttons misbehave.
* **Work out the real buffer** (USBD `EPIN[1].PTR`) before trusting a guessed variable.
* **Halting = SoftDevice assert.** Most "mysterious crashes" were self-inflicted.
* **Every direct POWER/NVMC/RADIO/NVIC access in vendor code is a latent fault** once the
  SoftDevice is on. Grep for the register addresses (`0x40000xxx`, `0x4001Exxx`, `0x40001xxx`)
  in the stock image when something resets.
* **The first USB attach after the HFXO takeover** needs the stock HFCLK refcount to be consistent
  (we release the stock count too); symptom otherwise: USB on the inaccurate internal oscillator.
* **Windows needs the stale device removed** after any key change.
* **Backup before every change**; this project made four named backups and used the original
  one as the ultimate safety net.
