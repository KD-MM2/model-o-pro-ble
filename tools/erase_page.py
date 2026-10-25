#!/usr/bin/env python3
"""erase_page.py bond|config [--go] -- erase the bond page (0xFD000) or the mode/config page (0xFE000) over SWD, then reset.
Default is a dry run that only prints the page's first words. These are the ONLY pages this tool can touch.
bond   -> mouse boots unbonded (purple blinks), host must re-pair      (the host's old entry becomes stale: remove it)
config -> mouse boots in the default mode (BLE) with pairing generation 0 (= the original BLE address)"""
import sys, time
from pyocd.core.helpers import ConnectHelper
PAGES = {'bond': 0xFD000, 'config': 0xFE000}
page = PAGES[sys.argv[1]]; go = '--go' in sys.argv
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
assert t.read32(0x10000100) == 0x52840
print('page 0x%x first words:' % page, [hex(x) for x in t.read_memory_block32(page, 4)])
if go:
    t.halt()
    t.write32(0x4001E504, 2)
    t.write32(0x4001E508, page)
    while not t.read32(0x4001E400): pass
    t.write32(0x4001E504, 0)
    while not t.read32(0x4001E400): pass
    assert t.read32(page) == 0xFFFFFFFF
    t.write32(0xE000ED0C, 0x05FA0004); time.sleep(0.3)
    print('erased + reset')
else:
    print('dry run (add --go)')
s.close()
