#!/usr/bin/env python3
"""fake_bonds.py save <file> | restore <file> | fill <n_hosts> [--go] -- TEST AID for the multi-host logic (no second host needed).
save/restore: copy the 1 KB bond area (0xFD000..0xFD3FF, 4 slots) to/from a file.  fill N: keep real bonds, fabricate valid-looking bonds in
the empty slots among 0..N-1, clear the rest (random keys, so they never match a real host).  Writes through the NVMC with the CPU halted, then resets.  Bond page only."""
import sys, time, struct, os
from pyocd.core.helpers import ConnectHelper
PAGE = 0xFD000
def rec_sum(w, n):
    a = 0x5A5A1234
    for x in w[:n]:
        a = ((a << 1 | a >> 31) & 0xFFFFFFFF) ^ x
    return a
def fake(i):
    r = [0] * 64
    r[0] = 0xB0DD0001
    for k in range(2, 9): r[k] = int.from_bytes(os.urandom(4), 'little')
    r[9] = 0 | ((i + 1) << 16)                     # sa_len 0, pairing seq
    r[1] = rec_sum(r[2:32], 30)
    r[32] = 0x1D1D0002; r[40] = i; r[41] = 0       # nonce = slot index, no identity
    r[33] = rec_sum(r[34:42], 8)
    return r
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
assert t.read32(0x10000100) == 0x52840
cmd = sys.argv[1]
cur = list(t.read_memory_block32(PAGE, 256))
if cmd == 'save':
    open(sys.argv[2], 'wb').write(struct.pack('<256I', *cur)); print('saved')
    sys.exit(0)
if cmd == 'restore': new = list(struct.unpack('<256I', open(sys.argv[2], 'rb').read()))
else:
    n = int(sys.argv[2]); new = [0xFFFFFFFF] * 256
    for i in range(4):
        if i < n: new[64 * i:64 * i + 64] = cur[64 * i:64 * i + 64] if cur[64 * i] == 0xB0DD0001 else fake(i)
print('slots valid after:', [new[64 * i] == 0xB0DD0001 for i in range(4)])
if '--go' in sys.argv or cmd == 'restore':
    t.halt()
    t.write32(0x4001E504, 2); t.write32(0x4001E508, PAGE)
    while not t.read32(0x4001E400): pass
    t.write32(0x4001E504, 1)
    for k, w in enumerate(new):
        if w != 0xFFFFFFFF:
            t.write32(PAGE + 4 * k, w)
            while not t.read32(0x4001E400): pass
    t.write32(0x4001E504, 0)
    while not t.read32(0x4001E400): pass
    t.write32(0xE000ED0C, 0x05FA0004); time.sleep(0.3); print('written + reset')
else: print('dry run (add --go)')
s.close()
