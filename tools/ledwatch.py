#!/usr/bin/env python3
"""ledwatch.py [seconds] -- non-halting monitor of the two LEDs: duty values of the status LED (PWM0 buffer 0x20003270), the DPI LED (PWM1
buffer 0x20003278), whether both PWM peripherals are enabled, and the stock idle counter (0x20003048). Prints on change. Use it while lifting
the mouse / pressing DPI to see what the stock LED engine does."""
import sys, time
from pyocd.core.helpers import ConnectHelper
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 120
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000}); s.open(); t = s.target
T0 = time.time(); last = None
REG = (0x20003000, 0x400); prev_ram = bytes(t.read_memory_block8(*REG))
NOISE = set(range(0x20003048, 0x2000304C))   # stock idle counter
def lit(buf): return 'LIT' if any((buf[i] | buf[i + 1] << 8) & 0x7FFF for i in (0, 2, 4)) else 'dark'
while time.time() - T0 < secs:
    try:
        b0 = bytes(t.read_memory_block8(0x20003270, 8)); b1 = bytes(t.read_memory_block8(0x20003278, 8))
        ram = bytes(t.read_memory_block8(*REG))
        cur = (lit(b0), lit(b1), b1[:6].hex(), t.read32(0x4001C500), t.read32(0x40021500))
        if cur != last:
            ch = [(REG[0] + i, prev_ram[i], ram[i]) for i in range(REG[1]) if prev_ram[i] != ram[i] and REG[0] + i not in NOISE and not (0x20003270 <= REG[0] + i < 0x20003280)]
            if last is not None and ch: print('         stock RAM bytes that changed in the same poll: ' + ', '.join('%x:%02x->%02x' % c for c in ch[:14]) + (' ...' if len(ch) > 14 else ''), flush=True)
            print('%6.1fs status LED %-4s | DPI LED %-4s (%s) | PWM0 en=%d PWM1 en=%d | idle counter %d' % (time.time() - T0, cur[0], cur[1], cur[2], cur[3], cur[4], t.read32(0x20003048)), flush=True)
            last = cur
        prev_ram = ram
    except Exception as e:
        print('probe error', e)
    time.sleep(0.2)
s.close()
