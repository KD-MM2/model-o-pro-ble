#!/usr/bin/env python3
"""relocate.py — rebase golden_app.bin (0x6000) to NEW_BASE. Usage: relocate.py [new_base_hex] [out.bin]
Patch set = scanner MUST-CHANGE (vectors+pool) U filtered AMBIGUOUS words (scan.txt from rebase_scan.py),
minus false positives (string tails, instruction halfwords, constants); the packed RAM-init blob
(0x1C944) is decoded, its flash pointers patched, and re-packed (literal-only tokens) at the same place.
"""
import re, struct, sys, json
from unpack import unpack
B = 0x6000; BLOB = 0x1c944; BLOB_END = 0x1cc90
NEW = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x27000
OUT = sys.argv[2] if len(sys.argv) > 2 else 'build/golden_app_%x.bin' % NEW
D = NEW - B
g = bytearray(open('stock/golden_app.bin', 'rb').read())
t = open('tools/scan.txt').read()
H = lambda m: [(int(a, 16), int(v, 16)) for a, v in m]
amb = H(re.findall(r'^  (0x[0-9a-f]+): (0x[0-9a-f]+)$', t.split(' ambiguous words:')[1].split('===JSON')[0], re.M))
pool = H([(a, v) for a, v, _ in re.findall(r'^  (0x[0-9a-f]+): (0x[0-9a-f]+) -> (0x[0-9a-f]+)$', t.split('literal/data pool in-image')[1].split(' movw/movt')[0], re.M)])
vec = H(re.findall(r'^  (0x[0-9a-f]+) -> (0x[0-9a-f]+)$', t.split(' vectors:')[1].split(' literal/data')[0], re.M))
pr = lambda b: 0x20 <= b < 0x7f
REAL = {0x604c, 0x6050, 0x6058, 0x60ac, 0x60cc, 0x7374, 0x11c88, 0x1c71c, 0x1c72c}
def instr_tail(v):   # halfword instr (pop{..,pc}/b .) + zero pad
    return v >> 16 == 0 and (v >> 8) in (0xbd, 0xe7, 0xf8, 0x87, 0x81, 0x8f, 0xf3) or v == 0xf340
patch = {}
for a, v in pool + vec: patch[a] = v
excl = []
for a, v in amb:
    if a in REAL: patch[a] = v; continue
    why = None
    if v < 0x10000 and pr(v & 255) and pr(v >> 8): why = 'str'
    elif instr_tail(v): why = 'instr'
    elif v in (0xffff, 0x10000, 0x8000, 0x76a8, 0xda7a, 0x8200, 0x8201, 0x8202, 0x8400, 0x8401, 0x8402, 0x8403): why = 'const'
    elif a >= BLOB: why = 'blob'
    if why: excl.append((a, v, why))
    else: patch[a] = v
# second pass: every other aligned in-range word the scanner never claimed (pools hidden in mis-decoded code, data ptrs)
EXTRA_REAL = {(0xe19c, 0xe1bd), (0x1ac28, 0xf3a9), (0x1ac38, 0xf3d3), (0x1acd0, 0xf341), (0x1ace0, 0xf3fd), (0x1afd0, 0x8725), (0x1b010, 0x7d65), (0x78e4, 0xab45), (0x1c8d4, 0x8f2b)}
for a in range(B, BLOB, 4):
    v, = struct.unpack_from('<I', g, a - B)
    if a in patch or not (B <= v < BLOB_END): continue
    if (a, v) in EXTRA_REAL or (v >= 0x10000 and v != 0x11021): patch[a] = v
patch = {a: v for a, v in patch.items() if a < BLOB}
# literal words below 0x10000 inside code need an LDR-literal loader, else they are instruction halfwords (+pad) the scanner mis-claimed
ld = set()
for o in range(0, len(g) - 3, 2):
    h, l = struct.unpack_from('<HH', g, o)
    if h >> 11 == 9: ld.add(((B + o + 4) & ~3) + (h & 0xff) * 4)
    if (h & 0xff7f) == 0xf85f and (l >> 12) != 0xf:
        pc = (B + o + 4) & ~3; ld.add(pc + (l & 0xfff) if h & 0x80 else pc - (l & 0xfff))
for a in [a for a, v in patch.items() if 0x6100 <= a < 0x1a000 and v < 0x10000 and a not in ld and a not in REAL]:
    excl.append((a, patch.pop(a), 'noloader'))
patch[0x1c71c] = 0x64d4; patch[0x1c72c] = 0x7210
for a, v in sorted(patch.items()):
    assert B <= v < BLOB_END, (hex(a), hex(v))
    struct.pack_into('<I', g, a - B, v + D)
# INIT table + blob
src = bytes(g[BLOB - B:BLOB_END - B]); data, used = unpack(src, 0x8a8); data = bytearray(data[:0x8a8]); assert used >= len(src) - 4
RAMP = [0x200035f0, 0x200035f4, 0x200035f8, 0x20003664, 0x2000377c, 0x20003790, 0x20003794, 0x20003798,
        0x2000379c, 0x200037a0, 0x200037a4] + list(range(0x200037fc, 0x20003830, 4))
for r in RAMP:
    o = r - 0x20003000; v, = struct.unpack_from('<I', data, o)
    if B <= v < BLOB_END: struct.pack_into('<I', data, o, v + D)
    elif r != 0x20003830 - 4 and v: print('RAM ptr skipped', hex(r), hex(v))
packed = bytearray()
for i in range(0, len(data), 254):
    c = data[i:i + 254]; packed += bytes([0, len(c) + 1, 0]) + c
assert unpack(bytes(packed), 0x8a8)[0][:0x8a8] == bytes(data)
img = bytes(g[:BLOB - B]) + bytes(packed)
newend = NEW + len(img)
# entry0 src stays BLOB+D; entry1 src (bss, unused) -> new end
struct.pack_into('<I', img := bytearray(img), 0x1c720 - B, newend)
import os; os.makedirs(os.path.dirname(OUT) or '.', exist_ok=True)
open(OUT, 'wb').write(img)
json.dump({'patched': len(patch), 'excluded': [(hex(a), hex(v), w) for a, v, w in excl], 'newend': hex(newend)}, open(OUT + '.json', 'w'), indent=1)
print('patched', len(patch), 'excluded', len(excl), 'size', len(img), 'end', hex(newend))
