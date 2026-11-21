#!/usr/bin/env python3
"""nvmc_flash.py <hex|bin> [--go] [--include-sd] [--base 0x0] -- flash a hex through the nRF NVMC over SWD (any probe pyocd supports).
Default region: app only (>=0x27000, <0xFD000). --include-sd also writes MBR + SoftDevice (0x0..0x27000); needed only
for the very first install. Never touches the bond/config pages (0xFD000+) or UICR. Default is a dry run (reads only).
A .bin is loaded at --base (default 0): this is how a full-flash backup is restored (use --include-sd).
Uses the generic cortex_m pyocd target, so it also works with ST-Link V2 clones that fail with `-t nrf52840` (Bad AP)."""
import sys, time
from intelhex import IntelHex
from pyocd.core.helpers import ConnectHelper
LO, HI, PAGE = 0x27000, 0xFD000, 0x1000
NVMC_READY, NVMC_CONFIG, NVMC_ERASEPAGE = 0x4001E400, 0x4001E504, 0x4001E508
path = sys.argv[1]; go = '--go' in sys.argv
if '--include-sd' in sys.argv: LO = 0
if path.endswith('.bin'):
    ih = IntelHex(); ih.loadbin(path, offset=int(sys.argv[sys.argv.index('--base') + 1], 0) if '--base' in sys.argv else 0)
else:
    ih = IntelHex(path)
img = {}
for a in ih.addresses():
    if LO <= a < HI: img[a] = ih[a]
pages = sorted({a // PAGE for a in img})
print('image pages', hex(pages[0] * PAGE), '..', hex(pages[-1] * PAGE + PAGE - 1), len(pages), 'pages')
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
t.halt()
assert t.read32(0x10000100) == 0x52840, 'not an nRF52840'
def wait():
    n = 0
    while not t.read32(NVMC_READY):
        n += 1
        assert n < 100000, 'NVMC timeout'
todo = []
for p in pages:
    base = p * PAGE
    cur = bytes(t.read_memory_block8(base, PAGE))
    want = bytearray(cur)
    # bytes not in the image keep their current value only if the page is not erased; compare the image bytes only
    diff = any(cur[a - base] != img[a] for a in img if base <= a < base + PAGE)
    if diff: todo.append(p)
print('pages to rewrite:', [hex(p * PAGE) for p in todo])
if not go or not todo:
    print('dry run' if not go else 'nothing to do'); s.close(); sys.exit(0)
for p in todo:
    base = p * PAGE
    t.write32(NVMC_CONFIG, 2); wait()                 # erase enable
    t.write32(NVMC_ERASEPAGE, base); wait()
    t.write32(NVMC_CONFIG, 1); wait()                 # write enable
    words = []
    for off in range(0, PAGE, 4):
        w = 0xFFFFFFFF
        for k in range(4):
            a = base + off + k
            if a in img: w = (w & ~(0xFF << (8 * k))) | (img[a] << (8 * k))
        words.append(w)
    for off in range(0, PAGE, 4):
        if words[off // 4] != 0xFFFFFFFF:
            t.write32(base + off, words[off // 4]); wait()
    t.write32(NVMC_CONFIG, 0); wait()
    got = bytes(t.read_memory_block8(base, PAGE))
    bad = [hex(a) for a in img if base <= a < base + PAGE and got[a - base] != img[a]]
    print('page', hex(base), 'verify', 'OK' if not bad else 'FAIL ' + str(bad[:4]))
    assert not bad
t.write32(0xE000ED0C, 0x05FA0004)                     # SYSRESETREQ
time.sleep(0.3)
s.close()
print('flashed + reset')
