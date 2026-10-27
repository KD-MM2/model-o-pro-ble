# DISCLAIMER

**Read this before using anything in this repository.**

## Unofficial project

This is an unofficial, hobbyist reverse-engineering and modification project. It is **not
affiliated with, endorsed by, sponsored by, or approved by Glorious GaminG LLC or Nordic
Semiconductor ASA**. All trademarks, product names, and brand names are the property of
their respective owners.

## Use at your own risk — this can permanently destroy your hardware

Modifying the firmware of a computer mouse is not a software update. Performing the steps
in this repository **can and often does irreversibly brick the device**, and the hardware
work can damage it:

- The vendor bootloader on the flash cannot be recovered once erased. There is **no
  factory restore image**; a bad flash can only be undone with a working debug probe and
  a backup you made yourself, beforehand.
- Unlocking the flash protection (APPROTECT) is a **one-way, irreversible** operation.
- Opening the case, probing the battery, and soldering or pressure-clipping to the PCB
  test pads can destroy the mouse, its battery, or your mainboard. The logic levels are
  1.9 V; wrong wiring can short the battery — a **fire hazard**.
- The BLE functionality in this repository was developed and tested on **one single
  physical device**. Your unit, batch, OS, or firmware revision may behave differently.

## No warranty, no liability

THE SOFTWARE, DOCUMENTATION, AND HARDWARE INSTRUCTIONS IN THIS REPOSITORY ARE PROVIDED
"AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY — including loss of the device, loss of data, property damage, or lost
warranty coverage — arising from the use of or inability to use this project.

## Warranty and vendor support

Flashing modified firmware **voids the manufacturer's warranty** and will very likely
make Glorious support refuse any claim. Glorious' own software (e.g. CORE) may stop
working with, or actively damage, a modified device.

## Firmware and third-party code — not redistributed here

- No Glorious firmware is distributed in this repository. You must obtain any stock
  firmware image from Glorious yourself; those binaries remain © Glorious GaminG LLC.
- The SoftDevice S140 is © Nordic Semiconductor ASA and is subject to Nordic's own
  license terms; download it from Nordic's site (see `tools/fetch_softdevice.sh`). The
  headers vendored under `fw/sd_api/` are Nordic SDK files under Nordic's license.
- Scripts and tools in this repository are provided for research, education and
  interoperability.

## Regulatory

A modified radio stack is no longer the certified configuration the product was FCC /
CE / MIC certified with. You are responsible for your local regulations regarding radio
emission and device modification.

## Safety net

Before touching flash, make your own full backup of the original flash contents and keep
it somewhere safe — see [docs/03-backup-restore.md](docs/03-backup-restore.md). It is the
**only** way back.

By continuing past this file you acknowledge that you alone are responsible for the
outcome, on hardware you own and at your own risk.
