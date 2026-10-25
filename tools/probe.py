#!/usr/bin/env python3
"""probe.py <command> -- NON-HALTING inspection of the running mouse over SWD (halting makes the SoftDevice assert!).
  status   mode/SD flag, fault registers, HFXO state, BLE log counters, current-connection params
  mem A N  hex dump N bytes at address A
  w32 A V  write one word (RAM only; e.g. live-tune the chord masks, see docs)
  chord P0 P1      set the live mode-chord GPIO masks (hex, active-low inputs; 0 0 disables). Address comes from blob ENTRY[5]
  slowconn [I L T] request idle connection params now (I in 1.25 ms units, latency, timeout in 10 ms; default 12 20 400)
  reset    SYSRESETREQ
Uses the generic cortex_m target: works with ST-Link V2 clones and CMSIS-DAP probes."""
import sys
from pyocd.core.helpers import ConnectHelper
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
r32 = t.read32
cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
if cmd == 'status':
    print('SD enabled flag [0x20003830]  =', r32(0x20003830) & 0xFF, ' (1 = BLE mode, 0 = dongle mode)')
    print('vendor mode var [0x20003003]  =', t.read8(0x20003003), ' (1 = USB/BLE transport, 2 = 2.4G radio)')
    print('CFSR 0x%08x HFSR 0x%08x (both should be 0)' % (r32(0xE000ED28), r32(0xE000ED2C)))
    st = r32(0x4000040C)
    print('HFCLKSTAT 0x%08x -> HFXO %s' % (st, 'RUNNING' if st & 0x10000 else 'off'))
    print('config page 0xFE000: %s' % [hex(x) for x in t.read_memory_block32(0xFE000, 4)], '(C0DE0001, mode 1=BLE 2=DONGLE, ~mode, generation)')
    print('bond page   0xFD000: magic 0x%08x (B0DD0001 = bonded)' % r32(0xFD000))
    L = 0x2003F100
    names = {0x00: 'magic', 0x04: 'init stage/err (0x1000 = ok)', 0x08: 'BLE events seen', 0x80: 'hvx last result', 0x84: 'reports sent',
             0xC0: 'conn interval @connect', 0xC4: 'conn interval after update', 0xC8: 'slave latency', 0xD0: 'conn_param_update rc',
             0xD4: 'HFXO takeovers', 0x100: 'before_sleep calls', 0x108: 'before_sleep completed'}
    for o, n in names.items(): print('LOG+0x%03x %-30s = 0x%x' % (o, n, r32(L + o)))
elif cmd == 'mem':
    a, n = int(sys.argv[2], 0), int(sys.argv[3], 0)
    b = bytes(t.read_memory_block8(a, n))
    for i in range(0, n, 16): print('%08x  %s' % (a + i, b[i:i + 16].hex(' ')))
elif cmd == 'w32':
    t.write32(int(sys.argv[2], 0), int(sys.argv[3], 0))
elif cmd == 'chord':
    a = r32(0x40014)                               # blob ENTRY[5] = &S.chord_p0
    t.write32(a, int(sys.argv[2], 0)); t.write32(a + 4, int(sys.argv[3], 0))
    print('chord masks at 0x%08x set to P0=%s P1=%s' % (a, sys.argv[2], sys.argv[3]))
elif cmd == 'slowconn':
    L = 0x2003F100
    if len(sys.argv) > 2:
        for i, v in zip((0x38, 0x39, 0x3B), sys.argv[2:5]): t.write32(L + 4 * i, int(v, 0))
    t.write32(L + 4 * 0x3A, 1)                     # trigger: next tick calls request_slow_conn()
elif cmd == 'reset':
    t.write32(0xE000ED0C, 0x05FA0004)
s.close()
