#!/usr/bin/env python3
"""erase_page.py bond|config [--go] -- erase the bond page (0xF7000) or the mode/config page (0xF6000) over SWD, then reset.
Default is a dry run that only prints the page's first words. These are the ONLY pages this tool can touch.
bond   -> mouse boots unbonded (purple blinks), host must re-pair      (the host's old entry becomes stale: remove it)
config -> mouse boots in the default mode (BLE) with pairing generation 0 (= the original BLE address)"""
import sys
import swd
PAGES = {'bond': 0xF7000, 'config': 0xF6000}
page = PAGES[sys.argv[1]]; go = '--go' in sys.argv
s = swd.connect(); t = s.target
print('page 0x%x first words:' % page, [hex(x) for x in t.read_memory_block32(page, 4)])
if go:
    swd.stop(t)
    swd.erase_page(t, page)
    swd.reset(t)
    print('erased + reset')
else:
    print('dry run (add --go)')
s.close()
