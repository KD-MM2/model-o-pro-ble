# Bluetooth LE for the Glorious Model O Pro Wireless

Adds **Bluetooth Low Energy** (plus the existing USB cable and 2.4 GHz dongle modes) to a
Glorious Model O Pro Wireless (Nordic nRF52840) that shipped with a 2.4 GHz-only firmware.
It does this **by patching the stock firmware binary**, not by rewriting it: Nordic's
SoftDevice S140 7.3.0 is installed underneath the vendor app, the app is relocated to make
room, and a small (8 KB) BLE HID module is hooked into the vendor's own report pipeline.

> **Risk notice.** This writes to the mouse's flash over SWD. You must open the mouse and
> solder/clip to test pads. The vendor bootloader is not recoverable once erased. Read
> [docs/03-backup-restore.md](docs/03-backup-restore.md) *before* touching anything.
> Everything here is unofficial and unsupported by Glorious or Nordic. It voids your warranty.
> Full terms: [DISCLAIMER.md](DISCLAIMER.md).

## What you get

| Feature | Status | How it was verified |
|---|---|---|
| USB cable mode (258A:2015, stock behaviour) | works | enumerates on Linux; cursor, buttons, wheel confirmed by user |
| BLE mouse: motion, 8 buttons, wheel, horizontal pan | works | Windows host, cursor-delta and button-watch scripts + user |
| Motion smoothness | acceptable | 7.5 ms connection interval, ~72 reports/s measured |
| Bonding (pair once, reconnects by itself) | works | survives reset and reflash of the app |
| Battery level over BLE (Battery Service) | works | read from Windows through `ble_battery.py` |
| Mode switch BLE ⇄ 2.4 GHz dongle by button chord | works (BLE→dongle→BLE round trip) | real buttons, LED feedback seen |
| Wipe all hosts (new identity) by a 10 s button chord | works | purple LED blinks, Windows saw a new device |
| **Up to 4 hosts**: DPI + Left (3 s) adds one, DPI + Forward/Back (1 s) cycles through the stored ones | works with 2 real hosts (Windows PC + phone), ~2 s per switch | passive trace of the user's own switching, re-pairing keeps the slot; see [06](docs/06-user-guide.md#4-pairing) |
| USB priority (cable plugged → USB, else BLE) | works | plug/unplug on Linux and Windows |
| LED mode feedback (green / blue / purple blinks) | works | observed |
| USB unplug/replug after using Glorious CORE | works (a hard fault here was found and fixed 2026-10-27, see docs/14) | repeated cycles under a fault trap |
| Power: HF crystal off when idle, idle slave latency, slow advertising, real System OFF after the stock 7-minute timeout and wake on button | works | register state read over SWD; sleep/wake observed. **Current draw was never measured with a meter** |
| 2.4 GHz dongle mode | **not re-tested** after the relocation (the stock path is left untouched; the user said it was fine) | — |
| DPI-button click | works (it used to reboot the mouse; fixed) | — |
| Linux/macOS as BLE host | **not tested** (only Windows was used) | — |

## Repository map

```
README.md                 you are here
DISCLAIMER.md             unofficial project; bricking, warranty and licensing terms — read first
Makefile                  one-command wrappers: venv, backup, build, dry-run, flash, status
requirements.txt          Python deps (pyocd, intelhex, keystone, capstone, ziglang…)
docs/
  01-concepts.md          what the stock firmware is, why this approach, big picture
  02-prerequisites.md     hardware (probe, pads, wiring) and software setup
  03-backup-restore.md    READ FIRST: backup, restore, recovery
  04-build.md             step-by-step build, with expected outputs and hashes
  05-flashing.md          first install vs. normal update; ST-Link and CMSIS-DAP
  06-user-guide.md        using the mouse: modes, chords, LEDs, pairing, battery, power
  07-internals.md         memory map, hooks, report pipeline, pins, records (reference)
  08-debugging.md         how to inspect a live mouse safely, recipes, tuning hooks
  09-test-rig.md          the Windows BLE test rig (bleak + scheduled task)
  10-troubleshooting.md   symptom → cause → fix, and hard-won lessons
  11-history-and-next.md  how we got here, what is unverified, ideas for later
  12-usb-update-plan.md   proposal: update over USB with a copier bootloader (not started)
  13-open-issues.md       prioritised list of open tasks for the app image
  14-regression-checklist.md  static audit + on-hardware regression runs for rare stock paths
  appendix/               raw worklog and the SoftDevice bring-up report
fw/blehid/blehid.c        the BLE HID module (C, the only new "logic")
fw/blehid/link.ld         linker script (code at 0x40000, RAM at 0x2000B400)
fw/blehid/build.sh        compile with `zig cc` (pip-installable, no ARM toolchain needed)
fw/sd_api/                S140 API headers (needed to compile blehid.c)
tools/
  dump_flash.py           read-only 1 MB flash + UICR backup
  extract_stock.py        cut the stock app out of a dump → stock/golden_app.bin
  fetch_softdevice.sh     download + verify Nordic S140 7.3.0 hex
  relocate.py unpack.py   rebase the stock app 0x6000 → 0x27000
  rebase_scan.py scan.txt the relocation scanner and its saved output
  mkhex.py                base image: SoftDevice + relocated app (no BLE), for bring-up tests
  mk_ble.py               THE patcher: hooks, thunks, stub, final hex
  nvmc_flash.py           SWD flasher through the NVMC (works with ST-Link V2 clones)
  probe.py                non-halting status/memory/tuning tool
  watch.py                non-halting regression monitor (reboots, faults, USB/BLE/settings changes)
  faultcatch.py           halts on a real fault and prints id/pc/backtrace (find SoftDevice access violations)
  erase_page.py           erase only the bond or mode page
  fdis.py                 Thumb disassembler + xref finder for the stock app
  erase_page.py         erase one flash page over SWD (only the bond or mode record)
rig/windows/              BLE test-rig scripts for a Windows host (pair, cursor, battery, buttons)
stock/ vendor/ build/ backups/   git-ignored working dirs (your files go here)
```

## Quick start (the 10-command version)

Prerequisites: an nRF52840 SWD probe wired to the mouse's test pads
([docs/02](docs/02-prerequisites.md)), Linux with Python 3.10+, internet for two downloads.

```bash
git clone <this repo> && cd glorious-o-pro-ble
make venv && source .venv/bin/activate      # 1. tools
make backup                                  # 2. READ-ONLY full flash backup -> backups/<date>/
make stock BACKUP=backups/<date>             # 3. extract the stock app from YOUR dump
make softdevice                              # 4. download Nordic S140 7.3.0 (+ checksum, no UICR)
make build                                   # 5. relocate + build + patch -> build/…_ble.hex
make dry-run                                 # 6. shows which flash pages would change; writes nothing
make flash-first                             # 7. FIRST install only: MBR + SoftDevice + app
make status                                  # 8. non-halting health report (SD flag = 1, CFSR = 0)
# 9. pair "Model O PRO Wireless" in your OS Bluetooth settings (2 purple blinks = pairing)
# 10. later updates: edit fw/blehid/blehid.c, `make flash` (app region only, SoftDevice untouched)
```

Step 3 only works on a mouse that still runs the **stock** app at 0x6000. If your chip already
holds a SoftDevice (i.e. you ran this once), skip steps 3–4 and keep your existing `stock/` and
`vendor/` files.

Expected result: the build is deterministic. With the stock app
`sha256 18f8b30a…d165` (v1.00.00, 2022-08-10) and S140 hex `sha256 5f460d35…` the final image is

```
build/s140_730_golden27000_ble.hex  sha256 5f594448c9de6e2fe5e10351e0c66f6bfd4ec1c447cc7bd35ff3e89b5053ed64
```

(This was verified by rebuilding from a clean checkout in a fresh virtualenv.)

## Design rules (why the repo looks the way it does)

1. **Do not reinvent.** The vendor firmware already reads the sensor, debounces buttons, runs
   macros/remaps and DPI, builds the HID report and drives the LED. BLE is added purely as
   *another transport* for the vendor's finished 8-byte report. Our first attempt re-implemented
   motion/buttons and behaved badly; reusing the stock pipeline fixed it at once.
2. **Never destroy the way back.** Never chip-erase, never write UICR, never touch the vendor
   settings pages (0x8B000/0x8C000). A full flash image is the restore point.
3. **One probe user at a time.** Two SWD clients corrupt each other's writes.
4. **Never halt the CPU while the SoftDevice is running** (see
   [docs/08-debugging.md](docs/08-debugging.md)); halting makes the SoftDevice assert and gives
   misleading "crashes".

## Licensing / what is not in this repo

* The **stock vendor firmware** is Glorious's property and is **not** included. You extract it
  from your own mouse ([docs/04](docs/04-build.md)). Same for flash dumps (`backups/`).
* The Nordic **SoftDevice** hex is downloaded from the public Adafruit bootloader repository
  and is subject to Nordic's license; it is not included either.
* Code in `fw/` and `tools/` was written for this project; `fw/sd_api/` are Nordic's headers
  (BSD-style Nordic license, see the file headers).
