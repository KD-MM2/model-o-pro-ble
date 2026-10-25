#!/usr/bin/env python3
"""rebase_scan.py — deterministic relocation scanner for golden_app.bin
(Glorious Model O Pro, nRF52840, flat binary loaded at 0x6000, 93328 bytes).

Answers: which sites in the app image must change if the whole image is
rebased from 0x6000 to a new base (e.g. 0x27000 to make room for an
nRF52 MBR + S140 SoftDevice), and which do NOT.

Model: under a uniform shift D = new_base - 0x6000 of the entire image,
  * PC-relative encodings (B/BL/B.W/CBZ/ADR/ADRS/LDR-literal) resolve to
    target+D automatically  -> MUST NOT be patched.
  * ABSOLUTE encodings break -> MUST be patched:
      V  vector-table words pointing into the image
      P  literal-pool / data words holding in-image pointers
         (consumed via `LDR rX,[PC,#imm]`, LDR-PC veneers, `ldr rX,[pc]; bx rX`)
      M  MOVW/MOVT immediate pairs constructing in-image addresses
  * Words that merely *look* like in-image pointers inside unclaimed data
    are reported separately as AMBIGUOUS (same alignment/T-bit test).

Code map: recursive-descent Thumb-2 disassembly from roots (reset vector,
all vector-table handlers, entry 0x6200, entry literal 0xE860) following the
transitive B/BL/trampoline closure plus TBB/TBH jump tables; address-like
word runs after terminators are claimed as literal pools.  Unclaimed
regions are scanned word-wise for additional pointer candidates.

Also prints: full SVC census (imm -> call sites) and the RAM-ABI absolute
references (0x20000000 page) the app assumes.

Output: human-readable sections + JSON summary between ===JSON-BEGIN=== /
===JSON-END=== markers.  Deterministic (sorted).  Static-only; never
modifies the image.
"""
import struct, sys, json, collections
from capstone import *

IMG = sys.argv[1] if len(sys.argv) > 1 else \
    'stock/golden_app.bin'
BASE = 0x6000
NEW_BASE = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x27000

g = open(IMG, 'rb').read()
END = BASE + len(g)
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS | CS_MODE_V8)
md.detail = True


def w32(a):
    o = a - BASE
    return struct.unpack_from('<I', g, o)[0] if 0 <= o <= len(g) - 4 else None


def in_img(a):
    return a is not None and BASE <= a < END


def ram_abi(v):
    return v is not None and 0x20000000 <= v < 0x20000100


def ram_app(v):
    return v is not None and 0x20000100 <= v < 0x20040000


def mmio(v):
    return v is not None and (0x10000000 <= v < 0x10030000
                              or 0x40000000 <= v < 0x50200000
                              or 0xE0000000 <= v < 0xE0100000)


def code_ptr(v):
    return in_img(v) and (v & 1) == 1


def ptr_like(v):
    return (code_ptr(v) or in_img(v) or ram_abi(v) or ram_app(v)
            or mmio(v) or v in (0, 0xFFFFFFFF, 0x01000000))


def parse_imm(s):
    s = s.strip().lstrip('#')
    try:
        return int(s, 0)
    except ValueError:
        return None


def imm_in(s):
    """last '#0x..' immediate token in an operand string, or None"""
    idx = s.rfind('#')
    if idx < 0:
        return None
    tok = ''
    for ch in s[idx + 1:]:
        if ch in '0123456789abcdefxABCDEFX':
            tok += ch
        else:
            break
    return parse_imm(tok)


claimed = bytearray(len(g))     # 1=data/pool, 2=code
traversed = bytearray(len(g))   # forward flow already explored from this pc
code_bytes = 0


def claim(pc, size, kind=2):
    global code_bytes
    o = pc - BASE
    if 0 <= o < len(g):
        n = 0
        for k in range(min(size, len(g) - o)):
            if not claimed[o + k]:
                claimed[o + k] = kind
                if kind == 2:
                    n += 1
        code_bytes += n


def claim_data(pc, size):
    claim(pc, size, kind=1)


pool_words = {}        # addr -> value  (claimed literal pools)
orphan_ptrs = {}       # addr -> value  (unclaimed data words that look like in-image ptrs)
vec_ptrs = {}          # addr -> value  (vector table entries)
svc_sites = collections.defaultdict(list)
boot_svcs = []                     # (pc, imm) SVCs reachable from reset vector
BOOT = [True]                      # first walk pass = boot-only phase
movt_abs = []          # (site, value)
adr_sites = []         # (site, resolved_target)   PC-relative: invariant
ldr_lit = []           # (site, pool_addr, value)  PC-relative: invariant
branches = []          # (site, kind, target)      PC-relative: invariant
indirect = set()       # (site, text) unresolved indirect jumps
funcs = set()
visited = set()
movw = {}              # reg -> [value, site]
regmap = {}            # reg -> value (ldr-literal / movt results, for bx rX trampolines)


def drain_pools(pc):
    """Claim address-like word runs at 4-aligned pc (literal pools)."""
    while pc % 4 == 0:
        v = w32(pc)
        if v is None or not ptr_like(v):
            break
        claim_data(pc, 4)
        pool_words[pc] = v
        pc += 4
    return pc


def walk(start):
    start &= ~1
    if not in_img(start) or start in visited:
        return
    visited.add(start)
    funcs.add(start)
    pc = start
    while True:
        o = pc - BASE
        if o < 0 or o + 2 > len(g):
            return
        if traversed[o]:
            return
        ins = None
        for cand in md.disasm(g[o:o + 4], pc):
            ins = cand
            break
        if ins is None:
            traversed[o] = 1
            if pc % 4 == 0 and ptr_like(w32(pc)):
                claim_data(pc, 4)
                pool_words[pc] = w32(pc)
                pc += 4
                continue
            pc += 2
            continue
        traversed[o] = 1
        claim(ins.address, ins.size)
        mn, ops = ins.mnemonic, ins.op_str
        size = ins.size

        if mn == 'svc':                                   # SVC census
            v = imm_in(ops)
            if v is not None:
                svc_sites[v].append(pc)
                if BOOT[0]:
                    boot_svcs.append((pc, v))
            pc += size
            continue

        if mn in ('movw', 'mov'):                         # lo16 constructors
            parts = ops.split(',')
            if len(parts) >= 2 and parts[0].strip().startswith('r'):
                reg = parts[0].strip()
                imm = imm_in(ops) if 'lsl' not in ops else None
                if imm is not None:
                    movw[reg] = [imm & 0xFFFFFFFF, pc]
                else:
                    movw.pop(reg, None)
            pc += size
            continue
        if mn == 'movt':
            parts = [p.strip() for p in ops.split(',')]
            reg = parts[0] if parts else ''
            imm = None
            if len(parts) >= 3 and 'lsl' in parts[2]:
                imm = parse_imm(parts[1])
            elif len(parts) >= 2:
                imm = parse_imm(parts[1])
            if imm is not None and reg in movw:
                val = (movw[reg][0] & 0xFFFF) | (imm << 16)
                if ptr_like(val):
                    movt_abs.append((pc, val))
                regmap[reg] = val
                movw.pop(reg, None)
            pc += size
            continue

        if mn in ('adr', 'adrs'):                         # PC-relative, invariant
            t = imm_in(ops)
            if t is not None:
                if not in_img(t):
                    t = ((pc + 4) & ~3) + t if t < 0x10000 else None
                if t is not None:
                    adr_sites.append((pc, t))
            pc += size
            continue
        if mn == 'ldr' and '[pc' in ops.replace(' ', ''):
            base_tok = ops.split('[', 1)[1].split(']')[0] if '[' in ops else ''
            fields = [f.strip() for f in base_tok.split(',')]
            dest = ops.split(',')[0].strip()
            if len(fields) >= 2 and fields[0] == 'pc':
                off = parse_imm(fields[1])
                if off is not None:
                    lit = ((pc + 4) & ~3) + off
                    v = w32(lit)
                    ldr_lit.append((pc, lit, v))
                    if dest == 'pc':                      # LDR PC veneer
                        if code_ptr(v):
                            walk(v)
                        branches.append((pc, 'LDR-PC veneer', v))
                        pc = drain_pools(pc + size)
                        return
                    if code_ptr(v):
                        regmap[dest] = v
                    else:
                        regmap.pop(dest, None)
            pc += size
            continue

        if mn == 'bl':
            t = imm_in(ops)
            if t is not None and in_img(t):
                branches.append((pc, 'BL', t))
                walk(t)
            pc += size
            continue
        if mn == 'b':
            t = imm_in(ops)
            if t is not None and in_img(t):
                branches.append((pc, 'B', t))
                pc = drain_pools(pc + size)
                walk(t)
                return
            pc += size
            continue
        if mn in ('bx', 'blx'):
            if ops == 'lr':
                pc = drain_pools(pc + size)
                return
            t = regmap.get(ops.strip())
            if t is not None and in_img(t):
                branches.append((pc, mn, t))
                walk(t)
            else:
                indirect.add((pc, mn + ' ' + ops))
            if mn == 'bx':
                pc = drain_pools(pc + size)
                return
            pc += size
            continue
        if mn == 'pop' and 'pc' in ops:
            pc = drain_pools(pc + size)
            return
        if mn in ('tbb', 'tbh'):
            tab = pc + size
            k = 0
            while in_img(tab + k):
                b = g[tab + k - BASE]
                tgt = tab + 2 + b * 2
                if not (start - 0x800 < tgt < start + 0x2000):
                    break
                claim_data(tab + k, 1)
                if b and in_img(tgt):
                    walk(tgt)
                k += 1
                if k > 512:
                    break
            pc = drain_pools(tab + k)
            return
        if mn.startswith('b') and mn not in ('bl', 'blx', 'bx', 'b'):
            t = imm_in(ops)
            if t is not None and in_img(t):
                branches.append((pc, mn, t))
                walk(t)
            pc += size
            continue
        if mn in ('push', 'stmdb'):
            pc += size
            continue
        if mn not in ('movw', 'movt'):                    # clobbered dest reg
            first = ops.split(',')[0].strip()
            if first.startswith('r') or first in ('lr', 'sp', 'pc'):
                movw.pop(first, None)
                regmap.pop(first, None)
        pc += size


# ------------------------------------------------------------------- roots
sys.setrecursionlimit(100000)
sp0, reset = struct.unpack_from('<II', g, 0)
walk(reset)                                    # boot-only pass (BOOT[0] True)
BOOT[0] = False
for off in range(0, 0x100, 4):
    v = struct.unpack_from('<I', g, off)[0]
    if in_img(BASE + off):
        vec_ptrs[BASE + off] = v
    if in_img(v) and (v & 1):
        walk(v)
walk(0x6200)

# Raw SVC opcode census over bytes never claimed by walk()
raw_svc = {}
for off in range(0, len(g) - 1, 2):
    if claimed[off]:
        continue
    h = struct.unpack_from('<H', g, off)[0]
    if (h & 0xFF00) == 0xDF00:
        imm = h & 0xFF
        raw_svc.setdefault(imm, []).append(BASE + off)
        svc_sites[imm].append(BASE + off)

# ------------------------------------------------------- data region scan
for off in range(0, len(g) - 3, 4):
    if any(claimed[off + k] for k in range(4)):
        continue
    v = w32(BASE + off)
    if in_img(v):
        orphan_ptrs[BASE + off] = v

# --------------------------------------------------------------- classify
must_vec = {a: v for a, v in vec_ptrs.items() if in_img(v)}
must_pool_img = {a: v for a, v in pool_words.items() if in_img(v)}
must_movt = [(a, v) for a, v in movt_abs if in_img(v)]
ambiguous = dict(sorted(orphan_ptrs.items()))
ramabi_pool = {a: v for a, v in pool_words.items() if ram_abi(v) or ram_app(v)}

total_must = len(must_vec) + len(must_pool_img) + len(must_movt)

# Nordic S140 SVC ABI cross-check (official-header-derived tables, if present)
SD_TABLES = {
    '6.1.1': '/home/kaotd/Workspaces/mouse/_re_work/s140/svc_table_s140_6.1.1.json',
    '7.3.0': '/home/kaotd/Workspaces/mouse/_re_work/s140/svc_table_s140_7.3.0.json',
}
sd_match, sd_names, sd_invalid = {}, {}, []
for _ver, _p in SD_TABLES.items():
    try:
        _t = {int(k): v for k, v in json.load(open(_p)).items()}
        _hit = [i for i in svc_sites if i in _t]
        sd_match[_ver] = {'hit': len(_hit), 'total': len(svc_sites)}
        if _ver == '7.3.0':
            sd_names = {hex(i): _t[i][1] for i in sorted(svc_sites) if i in _t}
            sd_invalid = [hex(i) for i in sorted(svc_sites) if i not in _t]
    except Exception:
        sd_match[_ver] = None

out = {
    'image': IMG, 'base': hex(BASE), 'end': hex(END), 'size': len(g),
    'new_base': hex(NEW_BASE),
    'code_bytes': code_bytes,
    'code_pct': round(100.0 * code_bytes / len(g), 1),
    'functions': len(funcs),
    'svc_kinds': len(svc_sites),
    'svc_total_sites': sum(len(v) for v in svc_sites.values()),
    'svc_imms': {hex(k): len(v) for k, v in sorted(svc_sites.items())},
    'must_change': {
        'vector_table_ptrs': len(must_vec),
        'literal_pool_ptrs': len(must_pool_img),
        'movt_pairs': len(must_movt),
        'TOTAL': total_must,
    },
    'invariant_pc_relative': {
        'branches': len(branches),
        'ldr_literal': len(ldr_lit),
        'adr': len(adr_sites),
    },
    'ambiguous_unclaimed_ptr_words': len(ambiguous),
    'pool_words_total': len(pool_words),
    'ram_abi_pool_words': {hex(a): hex(v) for a, v in sorted(ramabi_pool.items())},
    'raw_svc_sites': {hex(k): [hex(a) for a in v] for k, v in sorted(raw_svc.items())},
    'boot_reachable_svcs': [[hex(a), hex(v)] for a, v in boot_svcs],
    'nordic_sd_svc_match': sd_match,
    'nordic_svc_names_730': sd_names,
    'nordic_svc_invalid_730': sd_invalid,
}

print('=== rebase_scan ===')
print('image %s base %#x end %#x size %d  ->  new base %#x'
      % (IMG, BASE, END, len(g), NEW_BASE))
print('code claimed: %d B (%.1f%%) in %d functions'
      % (code_bytes, 100.0 * code_bytes / len(g), len(funcs)))
print('\nMUST CHANGE (absolute encodings):')
print('  vector-table in-image pointers : %d' % len(must_vec))
print('  literal-pool/data in-image ptrs: %d' % len(must_pool_img))
print('  MOVW/MOVT in-image constructors: %d' % len(must_movt))
print('  TOTAL                          : %d' % total_must)
print('\nINVARIANT (PC-relative, must NOT change):')
print('  branches B/BL(.W/cond)         : %d' % len(branches))
print('  LDR literal loads              : %d' % len(ldr_lit))
print('  ADR/ADRS                       : %d' % len(adr_sites))
print('\nAMBIGUOUS unclaimed in-image pointer words: %d' % len(ambiguous))
print('unresolved indirect branch sites : %d' % len(indirect))
print('\nSVC CENSUS (%d kinds, %d sites):'
      % (len(svc_sites), sum(len(v) for v in svc_sites.values())))
for imm in sorted(svc_sites):
    print('  svc #0x%02X : %3d sites @ %s' % (imm, len(svc_sites[imm]),
          ' '.join('%x' % s for s in sorted(svc_sites[imm])[:8])))
print('\nBoot-path (reset-reachable) SVC sites: %d' % len(boot_svcs))
for a, v in boot_svcs:
    print('  svc #0x%02X @ %s' % (v, hex(a)))
print('\nNORDIC S140 ABI match (app svc numbers vs official header tables):')
for _ver in sorted(sd_match):
    _m = sd_match[_ver]
    print('  S140 v%s: %s' % (_ver, '%d/%d' % (_m['hit'], _m['total']) if _m else 'table not found'))
if sd_invalid:
    print('  numbers NOT in S140 7.3.0 table: %s' % ' '.join(sd_invalid))
print('\nRAM-ABI/RAM pool words: %d' % len(ramabi_pool))
for a, v in sorted(ramabi_pool.items()):
    print('  [%s] = %s' % (hex(a), hex(v)))

print('\nMUST-CHANGE detail:')
print(' vectors:')
for a, v in sorted(must_vec.items()):
    print('  %s -> %s' % (hex(a), hex(v)))
print(' literal/data pool in-image pointers (addr: value -> new):')
for a, v in sorted(must_pool_img.items()):
    print('  %s: %s -> %s' % (hex(a), hex(v), hex(v - BASE + NEW_BASE)))
print(' movw/movt:')
for a, v in sorted(movt_abs):
    print('  %s: %s' % (hex(a), hex(v)))
print(' ambiguous words:')
for a, v in sorted(ambiguous.items()):
    print('  %s: %s' % (hex(a), hex(v)))

print('\n===JSON-BEGIN===')
print(json.dumps(out, indent=1, sort_keys=True))
print('===JSON-END===')
