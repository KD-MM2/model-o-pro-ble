#!/bin/bash
# Download the Nordic S140 7.3.0 SoftDevice hex (MBR + SD, no UICR records) and verify its checksum.
set -e
cd "$(dirname "$0")/.."
F=vendor/s140_nrf52_7.3.0_softdevice.hex
URL=https://raw.githubusercontent.com/adafruit/Adafruit_nRF52_Bootloader/master/lib/softdevice/s140_nrf52_7.3.0/s140_nrf52_7.3.0_softdevice.hex
[ -f "$F" ] || curl -fL "$URL" -o "$F"
echo "$(sha256sum "$F")"
echo "expected sha256 prefix: 5f460d35  (segments 0x0-0xB00 MBR and 0x1000-0x26498 SD; must contain NO record at 0x10001000+)"
grep -q ':020000041000' "$F" && { echo "REFUSING: hex contains UICR records"; exit 1; } || echo "no UICR records: OK"
