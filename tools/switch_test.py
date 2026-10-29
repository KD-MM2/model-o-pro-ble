#!/usr/bin/env python3
"""switch_test.py [rounds] -- hands-off measurement of host switching with two REAL hosts (do not touch the mouse or re-pair meanwhile).
Uses the SWD test hook (LOG[0x3C]) to switch, then for each switch prints: time until the new host is connected, the address the SoftDevice
really advertises (sd_ble_gap_adv_addr_get, LOG[0x3D..3F]) against the address expected for that slot, and, if no connection after
10 s, what a BLE scan from the Windows rig (WIN_HOST, default g15) sees. Anomalies (bond change, unexpected target) are flagged."""
import sys, time, os, subprocess, re
from pyocd.core.helpers import ConnectHelper
rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 4
L = 0x2003F100
WIN = os.environ.get('WIN_HOST', 'g15'); WUSER = os.environ.get('WIN_USER', 'KaoTD')
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000}); s.open(); t = s.target
def st():
    v = t.read32(L + 0xB4); return (v >> 8) & 0xFF, (v >> 16) & 0xFF, v >> 24
def expected(slot):
    gen = t.read32(0xFE00C); lo0 = t.read32(0x100000A4); hi = t.read32(0x100000A8)
    w = t.read_memory_block32(0xFD000 + 256 * slot, 64); n = w[40] if w[32] == 0x1D1D0002 else 0
    lo = (lo0 ^ ((gen * 0x9E3779B1) & 0xFFFFFFFF) ^ ((n * 0x85EBCA6B) & 0xFFFFFFFF)) & 0xFFFFFFFF
    a = [lo & 255, (lo >> 8) & 255, (lo >> 16) & 255, (lo >> 24) & 255, hi & 255, ((hi >> 8) | 0xC0) & 255]
    return ':'.join('%02X' % x for x in reversed(a))
def actual():
    lo, hi, rc = t.read32(L + 0xF4), t.read32(L + 0xF8), t.read32(L + 0xFC)
    a = [lo & 255, (lo >> 8) & 255, (lo >> 16) & 255, (lo >> 24) & 255, hi & 255, (hi >> 8) & 255]
    return ':'.join('%02X' % x for x in reversed(a)), rc
def bonds():
    return tuple(t.read_memory_block32(0xFD000 + 256 * i + 28, 1)[0] & 0xFFFF for i in range(2))   # ediv word of each slot
def scan():
    cmd = 'C:\\Users\\%s\\blevenv\\Scripts\\python.exe C:\\Users\\%s\\ble_scan.py "Model O" 6' % (WUSER, WUSER)
    try:
        return subprocess.run(['ssh', '-o', 'ConnectTimeout=5', WIN, cmd], capture_output=True, text=True, timeout=40).stdout
    except Exception as e:
        return 'scan failed: %s' % e
b0 = bonds(); print('bonds (ediv)', b0, 'start state target/slot/conn', st(), flush=True)
cur0 = st()[0]
for rnd in range(rounds):
    for want in (1 - cur0, cur0):   # always start by switching AWAY from the host we are on
        if bonds() != b0: print('!! bond records changed during the test (someone re-paired) -> results void', bonds()); b0 = bonds()
        while st()[0] != want:
            t.write32(L + 0xF0, 1)                      # one press; wait until the firmware consumed it (the main loop may idle for a while)
            for _ in range(100):
                if t.read32(L + 0xF0) == 0: break
                time.sleep(0.1)
            time.sleep(0.5)
        t0 = time.time(); seen_down = False; res = None; scanned = False
        while time.time() - t0 < 45:
            tg, sl, c = st()
            if tg != want: print('!! target moved to', tg, '(someone pressed a button?)'); break
            if not c: seen_down = True
            if c and sl == want and seen_down: res = time.time() - t0; break
            if not c and seen_down and not scanned and time.time() - t0 > 10:
                scanned = True; a, rc = actual()
                print('   no link after 10 s: SoftDevice advertises %s (rc %#x), expected %s' % (a, rc, expected(want)), flush=True)
                print('   g15 scan sees: ' + ' | '.join(l.strip() for l in scan().splitlines()[-4:]), flush=True)
            time.sleep(0.25)
        a, rc = actual()
        print('round %d -> host %d: %s   [advertised %s expected %s rc %#x]' % (rnd + 1, want + 1, ('connected after %.1f s' % res) if res else 'NOT connected in 45 s', a, expected(want), rc), flush=True)
        time.sleep(3)
s.close()
