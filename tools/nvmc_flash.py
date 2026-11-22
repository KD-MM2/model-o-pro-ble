#!/usr/bin/env python3
"""nvmc_flash.py FILE [FILE ...] [--go] [--include-sd] [--include-bootloader] [--base ADDR] -- write .hex/.bin files
through the nRF NVMC over SWD (any probe pyocd supports; ST-Link V2 clones fail with `-t nrf52840`, so the generic
cortex_m target is used). Default is a dry run that only compares.

Regions written (everything else in the files is ignored):
  0x27000-0xF4FFF  app                                          always
  0xFE000-0xFFFFF  bootloader settings page (app version, CRC)  always (build/settings.hex; ignored by a mouse without
                   and its backup copy in the MBR parameter page the bootloader; see tools/mk_dfu.py for why both)
  0x00000-0x26FFF  MBR + SoftDevice                             only with --include-sd (very first install)
  0xF8000-0xFDFFF  bootloader                                   only with --include-bootloader
Never written: the records 0xF5000-0xF7FFF (bond, config), UICR.
A .bin is loaded at --base (default 0), e.g. to restore a full-flash backup (with --include-sd)."""
import sys
from intelhex import IntelHex
import swd

args = [a for a in sys.argv[1:]]
go = '--go' in args
base = int(args[args.index('--base') + 1], 0) if '--base' in args else 0
files = [a for i, a in enumerate(args) if not a.startswith('--') and (i == 0 or args[i - 1] != '--base')]
regions = [(0x27000, 0xF5000), (0xFE000, 0x100000)]
if '--include-sd' in args: regions.append((0x0, 0x27000))
if '--include-bootloader' in args: regions.append((0xF8000, 0xFE000))

img = {}
for f in files:
    ih = IntelHex()
    if f.endswith('.bin'): ih.loadbin(f, offset=base)
    else: ih.loadhex(f)
    for a in ih.addresses():
        if any(lo <= a < hi for lo, hi in regions): img[a] = ih[a]
pages = swd.pages_of(img)
print('image pages', ', '.join('%#x' % p for p in pages[:3]), '...', '%#x' % pages[-1], '(%d pages)' % len(pages))

s = swd.connect(); t = s.target
todo = [p for p in pages if swd.page_differs(t, p, img)]
print('pages to rewrite:', [hex(p) for p in todo])
if not go or not todo:
    print('dry run' if not go else 'nothing to do'); s.close(); sys.exit(0)
swd.stop(t)
for p in todo:
    swd.program_page(t, p, {a: v for a, v in img.items() if p <= a < p + swd.PAGE})
    print('page %#x written, verify OK' % p)
swd.reset(t)
s.close()
print('flashed + reset')
