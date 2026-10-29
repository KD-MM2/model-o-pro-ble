#!/usr/bin/env python3
"""switch_trace.py [switches] [gap_s] -- press the host-switch hook `switches` times, `gap_s` apart, and log EVERYTHING with timestamps:
BLE event ids (ring), target/slot/connected, the advertised address, and the state of the chord buttons (DPI, FORWARD, BACK, LEFT, RIGHT)
so a physical button press (the user) can be told apart from the script. Events 0x55/0x57 (report sent) are hidden."""
import sys, time
from pyocd.core.helpers import ConnectHelper
n_sw = int(sys.argv[1]) if len(sys.argv) > 1 else 6
gap = float(sys.argv[2]) if len(sys.argv) > 2 else 15
L = 0x2003F100
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000}); s.open(); t = s.target
T0 = time.time()
def now(): return '%6.1fs' % (time.time() - T0)
def st():
    v = t.read32(L + 0xB4); return (v >> 8) & 0xFF, (v >> 16) & 0xFF, v >> 24, v & 0xFF
def btn():
    i0 = t.read32(0x50000510); i1 = t.read32(0x50000810)
    names = []
    if not i1 & 1: names.append('DPI')
    if not i0 & (1 << 10): names.append('FWD')
    if not i0 & (1 << 9): names.append('BACK')
    if not i1 & (1 << 15): names.append('LEFT')
    if not i1 & (1 << 13): names.append('RIGHT')
    return '+'.join(names)
n0 = t.read32(L + 8); last = None; lastb = ''
next_press = T0 + 3; presses = 0
while presses < n_sw or time.time() < next_press + gap:
    if presses < n_sw and time.time() >= next_press:
        t.write32(L + 0xF0, 1); presses += 1; next_press += gap; print(now(), '--- script: switch hook press #%d' % presses, flush=True)
    cur = st(); b = btn(); n = t.read32(L + 8)
    ev = [t.read32(L + 12 + 4 * (k & 15)) for k in range(max(n0, n - 16), n)]
    ev = ['%#x' % e for e in ev if e not in (0x55, 0x57)]
    n0 = n
    if b != lastb: print(now(), 'buttons held: %s' % (b or '(none)'), flush=True); lastb = b
    if cur != last or ev:
        print(now(), 'target=%d slot=%#x conn=%d pairing=%d %s' % (cur[0], cur[1], cur[2], cur[3], ('events ' + ' '.join(ev)) if ev else ''), flush=True); last = cur
    time.sleep(0.1)
print('adv addr %08x%08x rc %#x' % (t.read32(L + 0xF8), t.read32(L + 0xF4), t.read32(L + 0xFC)))
s.close()
