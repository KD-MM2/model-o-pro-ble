#!/usr/bin/env python3
"""dump_flash.py <outdir> -- read-only backup of the whole nRF52840 flash (1 MB) + UICR over SWD (does not halt for long, never writes).
Writes <outdir>/full_flash_1MB.bin, <outdir>/uicr.bin and SHA256SUMS. Works with any probe (generic cortex_m target)."""
import sys, os, hashlib
from pyocd.core.helpers import ConnectHelper
out = sys.argv[1] if len(sys.argv) > 1 else 'backups/' + __import__('time').strftime('%Y-%m-%d-%H%M')
os.makedirs(out, exist_ok=True)
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
assert t.read32(0x10000100) == 0x52840, 'not an nRF52840 (FICR.INFO.PART)'
print('APPROTECT (UICR 0x10001208) = 0x%08x' % t.read32(0x10001208))
flash = bytearray()
for a in range(0, 0x100000, 0x10000):
    flash += bytes(t.read_memory_block8(a, 0x10000)); print('.', end='', flush=True)
uicr = bytes(t.read_memory_block8(0x10001000, 0x1000))
s.close()
open(out + '/full_flash_1MB.bin', 'wb').write(flash); open(out + '/uicr.bin', 'wb').write(uicr)
sums = ''.join('%s  %s\n' % (hashlib.sha256(d).hexdigest(), n) for n, d in (('full_flash_1MB.bin', flash), ('uicr.bin', uicr)))
open(out + '/SHA256SUMS', 'w').write(sums)
print('\n' + sums + 'saved in ' + out)
