# Bluetooth LE for the Glorious Model O Pro Wireless — minimal version

Adds a Bluetooth LE mouse mode to a Glorious Model O Pro Wireless (Nordic nRF52840) by **patching the stock firmware
binary**: Nordic's SoftDevice S140 7.3.0 is installed under the vendor app, the app is moved up to make room, and a
small BLE module (`fw/blehid/blehid.c`, about 4 KB) is hooked into the vendor's own report pipeline. Everything else
(sensor, buttons, DPI, Glorious CORE settings, LEDs, battery measurement, sleep) is the vendor firmware, unchanged.

This branch is the minimal version (one host, no power optimisations, no debug hooks) plus Nordic's secure DFU
bootloader, so that later updates go over Bluetooth from a phone instead of SWD ([DFU bootloader](#dfu-bootloader)).
Read [DISCLAIMER.md](DISCLAIMER.md) first. You need SWD access (open the mouse) and a probe (ST-Link V2 clone or
CMSIS-DAP) for the first install.

> **Status:** the BLE firmware without the bootloader was tested on a mouse (2026-11-22, image `c8979df5…`): RF boot,
> mode chord, new-host chord, pairing at 7.5 ms, reports, reconnect. This branch moves the two flash records and adds
> the DFU chord and the bootloader. Tested on a mouse (2026-11-22, app version 2611221405): SWD install with the
> records moved (the host reconnected with the moved bond), BLE DFU of the app from a phone (three times), DFU chord in
> BLE and in RF mode, mode switch to RF, DPI held at reset (DFU after ~2 s with the stock watchdog running), return to
> the app after 120 s idle in DFU mode, `make flash` over SWD (settings + backup copy kept by the bootloader across
> resets; app version 2611221523). **Not tested:** a short DPI tap at reset.

## Behaviour

| | |
|---|---|
| **Modes** | **RF** = the stock firmware as shipped (2.4 GHz dongle; USB when a data cable is plugged in). **BLE** = Bluetooth only: a cable charges, and the computer sees an idle USB mouse that never moves. |
| **Switch mode** | Hold **DPI + Back + Forward** for 3 s. The mouse stores the other mode and reboots. Works in both modes. |
| **Pairing** | One host. A mouse with no bonded host advertises as "Model O PRO Wireless" and accepts the first host that pairs (Just Works). While a host is bonded, other hosts are refused. |
| **New host** | Hold **Left + Right + DPI** for 3 s (BLE mode). The mouse forgets the host, takes a new BLE address (the old host cannot reconnect with its stale key; remove the old entry on that host), reboots and waits for the next host. |
| **Update mode** | Hold **DPI + Left + Back** for 3 s (both modes). The mouse reboots into the DFU bootloader, which advertises as "ModelO DFU" for 2 minutes. Recovery when the firmware itself does not run: hold **DPI** while waking/powering the mouse, for 2 s. |
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

Flash map:

| Range | Content |
|---|---|
| `0x00000–0x26FFF` | MBR + S140 7.3.0. MBR page word `0xFF8` = `0xF8000` once the bootloader is activated |
| `0x27000–0x3E206` | stock app (relocated) |
| `0x3F000–`, `0x40000–` | stub/thunks, BLE module |
| `0x8B000`, `0x8C000` | Glorious CORE settings (stock, not moved) |
| `0xF5000–0xF7FFF` | DFU app data area, never erased by an update: mode/generation record `0xF6000`, bond record `0xF7000` |
| `0xF8000–0xFDFFF` | DFU bootloader |
| `0xFE000` | MBR parameter page (bootloader settings backup) |
| `0xFF000` | bootloader settings (app version, size, CRC) |

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
make dry-run        # compares the app and the settings page with the chip, writes nothing
make flash-first    # first install: MBR + SoftDevice + app + settings page
make flash          # update over SWD: app region + bootloader settings page; records are kept
make status         # non-halting check: where the CPU runs, mode, faults, records, bootloader, logs
```

`tools/erase_page.py bond|config --go` erases the bond record or the mode record by hand.

**Coming from the main (multi-host) branch:** that build gave each host its own address. This one uses one address per
pairing generation, so the stored host will not find the mouse. After flashing, hold Left + Right + DPI for 3 s once and
pair again.

## DFU bootloader

Nordic's secure BLE DFU bootloader from the nRF5 SDK 17.1.0 (`examples/dfu/secure_bootloader/pca10056_s140_ble`),
built by `tools/mk_bootloader.py`. Every change to Nordic's example is listed there with the stock and the modified
behaviour:

| Stock example (devkit) | This mouse |
|---|---|
| 32 kHz crystal | internal RC oscillator, the stock firmware's SoftDevice clock settings |
| DFU button P0.25, pressed at boot | DPI button P1.00, **held 2 s** at boot (every button also wakes the mouse, which is a reset) |
| devkit LEDs on P0.13–P0.16 | no LEDs, no devkit pins touched |
| `CONFIG_GPIO_AS_PINRESET` (may write UICR) | removed |
| name "DfuTarg" | "ModelO DFU" |

Updates are signed with your key (ECDSA P-256), received into a second bank above the running app and copied over it
only after the signature and hash checked out, so an interrupted update leaves the old firmware working. The records in
`0xF5000–0xF7FFF` and the CORE settings are never touched.

**UICR is not written.** The MBR in S140 7.x reads the bootloader address from word `0xFF8` of its own page before it
looks at `UICR.BOOTLOADERADDR`; that word is erased on this mouse, so installing is a plain word write. Undo:
`make bootloader-deactivate` erases the bootloader's first page, and the MBR goes back to SoftDevice → app.

### Install (SWD, once)

```bash
make bootloader-tools   # nRF5 SDK, Arm GCC 10.3, nrfutil into vendor/ (sha256-checked)
make dfu-key            # ../_keys/dfu_private.pem: BACK IT UP, without it no update is accepted
make bootloader         # build/bootloader.hex
make bootloader-plan    # what will be written, no writes
make bootloader-install # copies the records to 0xF6000/0xF7000, writes app, settings, bootloader (not active yet)
make bootloader-test    # starts the bootloader in DFU mode: "ModelO DFU" must appear in the phone app
```

The bootloader's first run activates it: Nordic's `main()` writes `0xF8000`/`0xFE000` into the erased MBR page words
`0xFF8`/`0xFFC` (`nrf_bootloader_mbr_addrs_populate`). `make bootloader-activate` writes the same words without a test
run.

### Update (BLE, no SWD)

1. `make dfu` → `build/app_dfu.zip` (version = build time; older versions are refused).
2. Copy the zip to a phone with Nordic's **nRF Device Firmware Update** app (or nRF Connect).
3. Hold DPI + Left + Back for 3 s: the mouse leaves the host and reboots into DFU mode.
4. In the app pick "ModelO DFU" and the zip. After the transfer the mouse restarts with the new firmware and reconnects
   to its host (bond and mode are kept).

## Repository

```
Makefile                 build, flash and status targets
fw/blehid/blehid.c       the BLE module
fw/blehid/build.sh       compile with zig cc (pip-installable), link at 0x40000, RAM at 0x2000B400
fw/bootloader/           board definition for the bootloader build
fw/sd_api/               S140 7.3.0 API headers
tools/mk_ble.py          boot stub, thunks, patch table, final image
tools/mk_bootloader.py   Nordic bootloader build, with every change to the SDK example
tools/mk_dfu.py          app-only hex, bootloader settings page, signed DFU package
tools/install_bootloader.py  SWD install / activate / deactivate of the bootloader
tools/bl_launch.py       start the installed bootloader once over SWD (test before activating)
tools/swd.py             SWD helpers: NVMC erase/write with read-back, flash only (never UICR)
tools/nrfutil            runs vendor/bin/nrfutil nrf5sdk-tools
tools/fetch_bootloader_tools.sh
tools/relocate.py        moves the stock app from 0x6000 to 0x27000 (uses scan.txt, unpack.py)
tools/extract_stock.py   cuts the stock app out of a flash dump
tools/fetch_softdevice.sh
tools/dump_flash.py      read-only backup
tools/nvmc_flash.py      flashing through the NVMC (works with ST-Link V2 clones)
tools/erase_page.py      erase the bond or mode record
tools/probe.py           non-halting status
```
