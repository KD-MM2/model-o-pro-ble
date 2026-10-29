#!/usr/bin/env python3
"""cycle_test.py <fwd_steps> <back_steps> -- drive the host-switch logic over SWD (LOG[0x3C] hook) and print the selected slot (1-based host
number), its advertising-address seed and the connected flag after every step. Test aid for tools/fake_bonds.py."""
import sys, time
from pyocd.core.helpers import ConnectHelper
L = 0x2003F100
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
def state():
    st = t.read32(L + 0xB4)
    return (st >> 8) & 0xFF, t.read32(L + 0xB8), st >> 24, st & 0xFF
def step(c):
    t.write32(L + 0xF0, c)
    for _ in range(40):
        time.sleep(0.1)
        if t.read32(L + 0xF0) == 0: break
    time.sleep(0.6)
    return state()
tg, seed, conn, pr = state(); print('start: host', tg + 1, 'seed %08x conn %d' % (seed, conn))
seq = []
for name, c, n in (('fwd', 1, int(sys.argv[1])), ('back', 2, int(sys.argv[2]))):
    out = []
    for _ in range(n):
        tg, seed, conn, pr = step(c); out.append(tg + 1)
        print('  %s -> host %d  addr seed %08x  conn %d' % (name, tg + 1, seed, conn))
    print(name, 'sequence:', '->'.join(map(str, out)))
s.close()
