#!/usr/bin/env python3
"""mk_dfu.py KEY.pem [VERSION] -- from build/s140_730_golden27000_ble.hex make
  build/app.hex       the application region only (0x27000-), what the bootloader calls "bank 0"
  build/settings.hex  the bootloader settings page (0xFF000) describing build/app.hex: version, size, CRC, plus the same
                      page as its backup copy at 0xFE000 (MBR parameter page). Written over SWD together with the app
                      (make flash, make bootloader-install). Both copies are needed: while the backup is valid, the
                      bootloader takes the app version, bank and boot-validation fields from the backup (Nordic's
                      tamper protection, nrf_dfu_settings_reinit), so a new settings page alone would be reverted and
                      the new app's CRC would not match: the bootloader would stay in DFU mode instead of starting it.
  build/app_dfu.zip   the signed update package for a BLE DFU client (Nordic's "nRF Device Firmware Update" or
                      "nRF Connect" app), sent to the mouse while it is in DFU mode.
VERSION is the application version (default: the build time as YYMMDDHHMM). The bootloader refuses a package with a
lower version than the installed one (downgrade prevention), so a later build always carries a higher number.
"""
import os, subprocess, sys, time
from intelhex import IntelHex

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
NRFUTIL = os.path.join(ROOT, 'tools/nrfutil')
KEY = os.path.abspath(sys.argv[1])
VERSION = int(sys.argv[2]) if len(sys.argv) > 2 else int(time.strftime('%y%m%d%H%M'))
APP_START, APP_DATA = 0x27000, 0xF5000      # app region ends where the bootloader's app data area (records) starts
STOCK_SETTINGS = 0x8B000                    # Glorious CORE settings pages 0x8B000/0x8C000 (stock code, never moved)
SD_FWID = '0x0123'                          # S140 7.3.0 (SoftDevice info struct, 0x300C)

def out(name): return os.path.join(ROOT, 'build', name)

full = IntelHex(out('s140_730_golden27000_ble.hex'))
app = IntelHex()
for a in full.addresses():
    if APP_START <= a < APP_DATA: app[a] = full[a]
size = max(app.addresses()) + 1 - APP_START
# Dual-bank DFU receives the new image right above the current one: bank 1 starts at 0x27000 + (current size, page
# aligned) and spans the new image. Two images of at most 0x32000 bytes each end below the stock settings at 0x8B000.
assert size <= (STOCK_SETTINGS - APP_START) // 2, 'app is %#x bytes: a DFU could reach the CORE settings at 0x8B000' % size
app.write_hex_file(out('app.hex'))

subprocess.check_call([NRFUTIL, 'settings', 'generate', '--family', 'NRF52840', '--application', out('app.hex'),
                       '--application-version', str(VERSION), '--bootloader-version', '1', '--bl-settings-version', '2',
                       '--app-boot-validation', 'VALIDATE_GENERATED_CRC', out('settings.hex')],
                      stdout=subprocess.DEVNULL)
sh = IntelHex(out('settings.hex'))
st = sh.addresses()
assert 0xFE000 <= min(st) and max(st) < 0x100000, 'settings outside 0xFE000-0xFFFFF'
assert sh.tobinarray(start=0xFE000, size=0x400).tobytes() == sh.tobinarray(start=0xFF000, size=0x400).tobytes(), \
    'settings backup (0xFE000) is not a copy of the settings page (0xFF000)'

if os.path.exists(out('app_dfu.zip')): os.remove(out('app_dfu.zip'))
subprocess.check_call([NRFUTIL, 'pkg', 'generate', '--hw-version', '52', '--sd-req', SD_FWID,
                       '--application', out('app.hex'), '--application-version', str(VERSION),
                       '--app-boot-validation', 'VALIDATE_GENERATED_CRC', '--key-file', KEY, out('app_dfu.zip')],
                      stdout=subprocess.DEVNULL)
print('app %#x-%#x (%d bytes), version %d -> build/app.hex, build/settings.hex, build/app_dfu.zip' % (
    APP_START, APP_START + size - 1, size, VERSION))
