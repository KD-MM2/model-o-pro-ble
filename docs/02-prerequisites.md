# 02 — Prerequisites

## 1. Hardware

| Item | Notes |
|---|---|
| The mouse | Glorious Model O Pro Wireless, nRF52840. Charged battery (a flat battery looks like "dead mouse", we lost time to that). |
| An SWD probe | Either works: **ST-Link V2** (and clones, `0483:3748`) or a **CMSIS-DAP** probe such as a Raspberry Pi Pico running `debugprobe`. Only one tool may use it at a time. |
| Wire/clips + resistors | SWCLK and SWDIO need **470 Ω – 1 kΩ series resistors** (the mouse's logic rail is ~1.9 V — do not drive it hard). Do **not** power the mouse from the probe: power it from its own USB cable or battery. |
| A BLE test host | Windows was used (BLE adapter + `bleak`; exact build not recorded). Any BLE-capable OS can pair by hand; the automated rig in [09](09-test-rig.md) is Windows-only. |

### SWD test pads (as documented by the earlier session on this unit)

| Probe signal | Mouse pad |
|---|---|
| SWCLK | **TP17** |
| SWDIO | **TP9** |
| GND | **TP13** or **TP10** |

These came from the first hardware session (RP2040 probe) and were later reused with the
ST-Link; verify against your own board revision before soldering. Pads are on the main PCB,
so the shell has to be opened.

### Is the chip readable?

nRF52840 has `APPROTECT`. On a mouse straight from the factory the debug port may be
**locked** (UICR `APPROTECT @0x10001208 != 0xFFFFFFFF` on revisions that use the legacy
scheme). Unlocking is only possible through a **mass erase (ERASEALL)**, which destroys the
vendor bootloader at 0x0–0x5FFF and all settings, and that bootloader exists nowhere else.
The unit this project was developed on had already been unlocked in an earlier session, and
its chip read `APPROTECT = 0xFFFFFFFF` (open). `make backup` prints this value.

If your chip is locked, **stop and decide consciously**: after the erase you can no longer
use Glorious's USB firmware updater (it needs the vendor bootloader), and nothing in this
repo can recreate it. You can still run all of this repo; you just flash over SWD from then on.

## 2. Software

Linux host (developed on Kali, kernel 7.x). Required:

* Python 3.10+ with `venv`
* `curl`, `sha256sum`
* `llvm-objcopy` (the build script looks for `llvm-objcopy-21`, then `llvm-objcopy`; on
  Debian/Ubuntu/Kali: `sudo apt install llvm`). Everything else (compiler, linker) comes from pip.
* udev permission for your probe (no `sudo` needed for pyocd):

  ```bash
  # /etc/udev/rules.d/99-probe.rules
  SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="3748", MODE="0666"   # ST-Link V2
  SUBSYSTEM=="usb", ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="0004", MODE="0666"   # Pico debugprobe
  # optional, for the mouse's own HID interfaces:
  SUBSYSTEM=="hidraw", ATTRS{idVendor}=="258a", MODE="0666"
  sudo udevadm control --reload && sudo udevadm trigger
  ```

* Install the Python tools once:

  ```bash
  make venv && source .venv/bin/activate     # pyocd, intelhex, keystone, capstone, unicorn, ziglang
  ```

  `ziglang` (a pip wheel) gives `zig cc` + `ld.lld`, so **no arm-none-eabi-gcc is needed**.
  If you prefer GCC, edit `fw/blehid/build.sh`; the flags needed are `-mcpu=cortex-m4 -Os
  -ffreestanding -fno-builtin -fno-pic` and the linker script `fw/blehid/link.ld`.

## 3. Check the probe sees the chip (read-only)

```bash
source .venv/bin/activate
pyocd list                         # your probe should appear
python tools/probe.py mem 0x10000100 4
# 4 bytes: 40 28 05 00  -> FICR.INFO.PART = 0x52840  (nRF52840)
```

**ST-Link V2 clones and pyocd:** `pyocd ... -t nrf52840` fails with
`STLink error (29): Bad AP` because the nRF target class probes the CTRL-AP which those probes
can't reach. Every tool in this repo therefore uses the generic `cortex_m` target and
programs flash itself through the NVMC registers. CMSIS-DAP probes can use either.

## 4. Safety checklist before any write

- [ ] A full backup exists in `backups/<date>/` **and** a copy lives outside the repo.
- [ ] `sha256sum -c backups/<date>/SHA256SUMS` passes.
- [ ] The mouse is powered by its own cable/battery, probe wires have series resistors.
- [ ] No other program (vendor software, another agent, another terminal) is using the probe.
- [ ] You will **not** use `--erase chip` / `ERASEALL` and will **not** write UICR.
