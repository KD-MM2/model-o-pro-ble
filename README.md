# Bluetooth LE for the Glorious Model O Pro Wireless — minimal version

Adds a Bluetooth LE mouse mode to a Glorious Model O Pro Wireless (Nordic nRF52840) by **patching the stock firmware
binary**: Nordic's SoftDevice S140 7.3.0 is installed under the vendor app, the app is moved up to make room, and a
small BLE module (`fw/blehid/blehid.c`, about 4 KB) is hooked into the vendor's own report pipeline. Everything else
(sensor, buttons, DPI, Glorious CORE settings, LEDs, battery measurement, sleep) is the vendor firmware, unchanged.

This branch is the minimal version: one host, no power optimisations, no debug hooks.
Read [DISCLAIMER.md](DISCLAIMER.md) first. You need SWD access (open the mouse) and a probe (ST-Link V2 clone or CMSIS-DAP).

> **Status:** the image builds, every patch site is asserted against the stock bytes, and the new thunks were run in an
> emulator (unicorn) in both modes. This exact image has **not been run on a mouse yet.**

## Behaviour

| | |
|---|---|
| **Modes** | **RF** = the stock firmware as shipped (2.4 GHz dongle; USB when a data cable is plugged in). **BLE** = Bluetooth only: a cable charges, and the computer sees an idle USB mouse that never moves. |
| **Switch mode** | Hold **DPI + Back + Forward** for 3 s. The mouse stores the other mode and reboots. Works in both modes. |
| **Pairing** | One host. A mouse with no bonded host advertises as "Model O PRO Wireless" and accepts the first host that pairs (Just Works). While a host is bonded, other hosts are refused. |
| **New host** | Hold **Left + Right + DPI** for 3 s (BLE mode). The mouse forgets the host, takes a new BLE address (the old host cannot reconnect with its stale key; remove the old entry on that host), reboots and waits for the next host. |
| **Latency** | The mouse asks for a 7.5 ms connection interval (the BLE minimum) after connecting and again once the link is encrypted. The host decides; Windows accepted it in earlier tests. |
| **Battery** | Battery Service with the stock percentage. The stock value restarts at 100 after boot and after plugging/unplugging, then settles within ~25 s; the host sees those steps. |
| **Sleep** | The stock 7-minute idle sleep. A button press wakes the mouse (it reboots, as in stock). |

LED (status LED, the DPI LED is never touched):

| Pattern | Meaning |
|---|---|
| 2 × blue at boot | BLE mode, a host is bonded |
| 2 × purple at boot | BLE mode, no host: ready to pair |
| 2 × green at boot | RF mode |
| 1 × blue | host connected |
| 3 × purple | new-host chord accepted (reboots) |

Not supported over BLE: keyboard/media reports produced by button remaps or macros in Glorious CORE (only the mouse
report is carried). In BLE mode with a data cable attached, the stock firmware still sends those few reports over USB.

## What is changed in the stock firmware

All changes are made by `tools/mk_ble.py`; each one asserts the original bytes first. "SD on" = BLE mode (the
SoftDevice owns POWER, NVMC, RADIO, TIMER0; a direct access from the app is a fault). With the SoftDevice off every
thunk runs the stock instructions, so **RF mode behaves like the stock firmware**, plus the mode chord and the boot
blink. Addresses are stock ("orig") addresses.

| Orig | Stock behaviour | Modified behaviour |
|---|---|---|
| 0xE878 | boot calls 0x6F68 (USB/app init) | first reads the mode record: RF → mode-chord/LED init only; BLE → enable the SoftDevice, start BLE. Then 0x6F68 |
| 0xE92C | main loop calls 0x14AE4 (report flags) | calls the BLE module, which runs 0x14AE4 first, then chords, LED, BLE events |
| 0x6F94 | writes POWER.DCDCEN = 1 | SD on: `sd_power_dcdc_mode_set(1)` |
| 0xE888 | starts the 2.4 GHz radio and its TIMER0 when on battery | SD on: skipped |
| 0xABA0 | idle sleep: on battery writes POWER.SYSTEMOFF directly, else `sd_power_system_off` | SD on: `sd_power_system_off` |
| 0xABDA, 0xABDE | sleep preparation stops the 2.4 GHz radio | SD on: skipped |
| 0x19B84, 0x19B8C, 0x19B0E | 2.4 GHz link state machine (USB plug/unplug) powers the radio up/down | SD on: radio calls skipped, the mode-variable update kept |
| 0x14880 | CORE command 0xA0 (wireless parameters) restarts the radio | SD on: skipped |
| 0xBE88, 0xBEEE | settings flash: SoftDevice API only in the vendor's "mode 2", NVMC directly otherwise | always asks the SoftDevice whether it is enabled (the vendor's own test): on → SoftDevice API, off → NVMC |
| 0x14D68 | mouse report: USB if enumerated, else by the mode variable (2.4 GHz) | SD on: BLE only |

Flash map: MBR + S140 `0x0–0x26FFF`, stock app (relocated) `0x27000–0x3E206`, stub/thunks `0x3F000–`, BLE module
`0x40000–`, bond record `0xFD000`, mode/generation record `0xFE000`.

## Build

Needs Python 3.10+ and `llvm-objcopy` (`sudo apt install llvm`).

```bash
make venv && source .venv/bin/activate
make softdevice                          # downloads and verifies S140 7.3.0 into vendor/
make backup                              # FIRST: full read-only flash dump into backups/<date>/
make stock BACKUP=backups/<date>         # cuts stock/golden_app.bin (the vendor app) out of that dump
make build                               # -> build/s140_730_golden27000_ble.hex
```

The stock app must be version 1.00.00 (`stock/golden_app.bin`, sha256 `18f8b30a…`); another version stops at a patch
assertion. With that stock app and S140 7.3.0 the image is
`sha256 c8979df5c3b0787a04c689a7fce0a54fced5e5e50f520df23c07f126fa8a87cc`.

## Backup first

`make backup` reads the whole 1 MB flash and the UICR over SWD without writing anything. Keep that dump: it is the only
way back to the original firmware (the vendor bootloader is not recoverable once erased).

## Flash

```bash
make dry-run        # compares the image with the chip, writes nothing
make flash-first    # first install: MBR + SoftDevice + app
make flash          # later updates: app region only (0x27000–0xFD000); bond and mode records are kept
make status         # non-halting check: mode, faults, records, logs
```

`tools/erase_page.py bond|config --go` erases the bond record or the mode record by hand.

**Coming from the main (multi-host) branch:** that build gave each host its own address. This one uses one address per
pairing generation, so the stored host will not find the mouse. After flashing, hold Left + Right + DPI for 3 s once and
pair again.

## Repository

```
Makefile                 build, flash and status targets
fw/blehid/blehid.c       the BLE module
fw/blehid/build.sh       compile with zig cc (pip-installable), link at 0x40000, RAM at 0x2000B400
fw/sd_api/               S140 7.3.0 API headers
tools/mk_ble.py          boot stub, thunks, patch table, final image
tools/relocate.py        moves the stock app from 0x6000 to 0x27000 (uses scan.txt, unpack.py)
tools/extract_stock.py   cuts the stock app out of a flash dump
tools/fetch_softdevice.sh
tools/dump_flash.py      read-only backup
tools/nvmc_flash.py      flashing through the NVMC (works with ST-Link V2 clones)
tools/erase_page.py      erase the bond or mode record
tools/probe.py           non-halting status
```
