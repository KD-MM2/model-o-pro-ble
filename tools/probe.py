#!/usr/bin/env python3
"""probe.py [status | mem ADDR LEN | reset] -- NON-HALTING look at the running mouse over SWD.
Never halt the CPU while the SoftDevice runs: a halted SoftDevice asserts and the chip resets.
Uses the generic cortex_m pyocd target, so ST-Link V2 clones work too."""
import sys
from pyocd.core.helpers import ConnectHelper
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
r32 = t.read32
cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
if cmd == 'status':
    sd = t.read8(0x20003830)
    print('mode            : %s  (SoftDevice enabled flag [0x20003830] = %d)' % ('BLE' if sd else 'RF (stock)', sd))
    print('stock mode var  : %d  ([0x20003003]: 1 = on battery, 0 = USB attached)' % t.read8(0x20003003))
    print('fault registers : CFSR 0x%08x HFSR 0x%08x  (both 0 = no fault)' % (r32(0xE000ED28), r32(0xE000ED2C)))
    c = t.read_memory_block32(0xFE000, 4)
    ok = c[0] == 0xC0DE0001 and (c[1] ^ c[2]) == 0xFFFFFFFF
    print('config 0xFE000  : %s' % (('mode %d (1 = BLE, 2 = RF), pairing generation %d' % (c[1], c[3] if c[3] != 0xFFFFFFFF else 0))
                                     if ok else 'none (defaults: BLE, generation 0)'))
    print('bond 0xFD000    : %s' % ('a host is bonded' if r32(0xFD000) == 0xB0DD0001 else 'no bond (pairing allowed)'))
    S = 0x2003F000   # stub log, written by the SoftDevice bring-up in mk_ble.py (BLE mode only)
    print('stub log        : power_init %d, sdh_enable %d, cfg attr %d, cfg uuid %d, ble_enable %d, app RAM %#x, blehid_init %#x, %s' % (
        r32(S + 4), r32(S + 8), r32(S + 0xC), r32(S + 0x10), r32(S + 0x14), r32(S + 0x18), r32(S + 0x1C),
        'finished' if r32(S + 0x24) == 0xB1E0FFFF else 'NOT finished'))
    L = 0x2003F100   # blehid log, see LOG in fw/blehid/blehid.c
    n = r32(L + 8)
    print('blehid log      : magic %#x, init %#x (0x1000 = ok), %d BLE events, last: %s, last flash write %d (0 = ok)' % (
        r32(L), r32(L + 4), n, ' '.join('%#x' % r32(L + 12 + 4 * (k & 15)) for k in range(max(0, n - 8), n)), r32(L + 4 * 19)))
elif cmd == 'mem':
    a, n = int(sys.argv[2], 0), int(sys.argv[3], 0)
    d = bytes(t.read_memory_block8(a, n))
    for i in range(0, n, 16): print('%08x  %s' % (a + i, d[i:i + 16].hex(' ')))
elif cmd == 'reset':
    t.write32(0xE000ED0C, 0x05FA0004)
s.close()
