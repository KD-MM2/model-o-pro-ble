#!/usr/bin/env python3
"""pairwatch.py [seconds] -- non-halting monitor of the multi-host state: BLE event ring (LOG[3..18]), pairing window / target / slot /
connected (LOG[0x2D]), refused pairings (LOG[0x2C]), slot allocation (LOG[0x2B]), bond slot summary. Prints on change."""
import sys, time
from pyocd.core.helpers import ConnectHelper
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 120
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
L = 0x2003F100
t0 = time.time(); last = None; n0 = t.read32(L + 8)
def slots():
    out = []
    for i in range(4):
        w = t.read_memory_block32(0xFD000 + 256 * i, 10)
        out.append('-' if w[0] != 0xB0DD0001 else '%d(e%04x)' % (w[9] >> 16, w[7] & 0xFFFF))
    return ' '.join(out)
while time.time() - t0 < secs:
    try:
        n = t.read32(L + 8); st = t.read32(L + 0xB4); ref = t.read32(L + 0xB0); al = t.read32(L + 0xAC)
        ring = [t.read32(L + 12 + 4 * ((k) & 15)) for k in range(max(n0, n - 8), n)] if n != n0 else []
        cur = (st, ref, al, slots())
        ring = [e for e in ring if e not in (0x57, 0x55)]   # report-sent events (50/s) are noise
        if cur != last or ring:
            print('%6.1fs evts=%d pairing=%d target=%#x slot=%#x conn=%d refused=%d alloc=%#x slots[%s] new_events=%s' % (
                time.time() - t0, n, st & 0xFF, (st >> 8) & 0xFF, (st >> 16) & 0xFF, st >> 24, ref, al, cur[3], ['%#x' % e for e in ring]), flush=True)
            last = cur; n0 = n
    except Exception as e:
        print('probe error', e)
    time.sleep(0.3)
