#!/usr/bin/env python3
"""install_bootloader.py [--go] [--activate | --deactivate] -- install the DFU bootloader over SWD (once; later updates
go over BLE). Default is a dry run: it prints the plan and writes nothing.

--go writes, in this order, each step read back:
  1. records    earlier builds kept the config record at 0xFE000 and the bond record at 0xFD000, where the bootloader
                now lives: copy them to 0xF6000 / 0xF7000 (only into an empty page)
  2. app        build/app.hex (this branch: records at 0xF6000/0xF7000)                      0x27000-
  3. settings   build/settings.hex: version, size and CRC of build/app.hex at 0xFF000 and its backup copy at
                0xFE000 (MBR parameter page, where the old config record was)
  4. bootloader build/bootloader.hex                                                         0xF8000-0xFDFFF
  The MBR does not know the bootloader yet, so the mouse still boots MBR -> SoftDevice -> app. The first time the
  bootloader runs (tools/bl_launch.py, or step 5) Nordic's main() writes the step-5 words itself if they are erased.
--activate (with --go), after the steps above:
  5. writes 0xF8000 to 0xFF8 and 0xFE000 to 0xFFC in the MBR page. Both words are erased on a mouse that never had a
     bootloader, so these are plain word writes (no page erase). MBR 2.4.x prefers this word to UICR.BOOTLOADERADDR
     (MBR code 0x444) and starts the bootloader from the next reset on. UICR is not written.
--deactivate (with --go): erase the bootloader's first page 0xF8000. The MBR finds no bootloader there and boots the
  SoftDevice and the app as before (MBR code 0x45A -> 0x4E0). `--go` again reinstalls it."""
import sys
from intelhex import IntelHex
import swd

go, activate, deactivate = '--go' in sys.argv, '--activate' in sys.argv, '--deactivate' in sys.argv
BL, BL_END, MBR_PARAMS = 0xF8000, 0xFE000, 0xFE000
OLD_BOND, OLD_CFG, NEW_CFG, NEW_BOND = 0xFD000, 0xFE000, 0xF6000, 0xF7000
CFG_MAGIC, BOND_MAGIC = 0xC0DE0001, 0xB0DD0001

def load(path, lo, hi):
    ih = IntelHex(path)
    d = {a: ih[a] for a in ih.addresses()}
    assert d and all(lo <= a < hi for a in d), '%s has data outside %#x-%#x' % (path, lo, hi)
    return d

app = load('build/app.hex', 0x27000, 0xF5000)
settings = load('build/settings.hex', MBR_PARAMS, 0x100000)
boot = load('build/bootloader.hex', BL, BL_END)

s = swd.connect(); t = s.target
w = lambda a: t.read32(a)
words = lambda a, n: list(t.read_memory_block32(a, n))
erased = lambda a: all(x == 0xFFFFFFFF for x in t.read_memory_block32(a, swd.PAGE // 4))

if deactivate:
    print('bootloader first word %#x (0xffffffff = already inactive)' % w(BL))
    if go and w(BL) != 0xFFFFFFFF:
        swd.stop(t); swd.erase_page(t, BL); swd.reset(t); print('0xF8000 erased: MBR boots SoftDevice -> app')
    s.close(); sys.exit(0)

plan = []
cfg_old, bond_old = words(OLD_CFG, 4), words(OLD_BOND, 32)
if erased(NEW_CFG) and cfg_old[0] == CFG_MAGIC and (cfg_old[1] ^ cfg_old[2]) == 0xFFFFFFFF:
    plan.append(('copy config record 0xFE000 -> 0xF6000 (mode %d, generation %d)' % (cfg_old[1], cfg_old[3]),
                 lambda: swd.write_words(t, NEW_CFG, cfg_old)))
if erased(NEW_BOND) and bond_old[0] == BOND_MAGIC:
    plan.append(('copy bond record 0xFD000 -> 0xF7000', lambda: swd.write_words(t, NEW_BOND, bond_old)))
for name, data in (('app', app), ('settings', settings), ('bootloader', boot)):
    for p in swd.pages_of(data):
        if swd.page_differs(t, p, data):
            plan.append(('write %s page %#x' % (name, p),
                         lambda p=p, data=data: swd.program_page(t, p, {a: v for a, v in data.items() if p <= a < p + swd.PAGE})))
mbr_words = words(0xFF8, 2)
if activate:
    if mbr_words == [BL, MBR_PARAMS]:
        print('MBR page already points at the bootloader (0xFF8 = %#x, 0xFFC = %#x)' % tuple(mbr_words))
    else:
        assert mbr_words == [0xFFFFFFFF, 0xFFFFFFFF], 'MBR words 0xFF8/0xFFC hold %s: not touching them' % [hex(x) for x in mbr_words]
        plan.append(('ACTIVATE: write 0xFF8 = 0xF8000, 0xFFC = 0xFE000 (MBR page)',
                     lambda: swd.write_words(t, 0xFF8, [BL, MBR_PARAMS])))

print('MBR 0xFF8/0xFFC now: %#x %#x (0xffffffff = bootloader not active)' % tuple(mbr_words))
print('plan:' if plan else 'nothing to do'); [print('  ' + p[0]) for p in plan]
if go and plan:
    swd.stop(t)
    for name, step in plan:
        step(); print('done:', name)
    swd.reset(t)
    print('reset')
elif plan:
    print('dry run (add --go%s)' % ('' if activate else '; --activate makes the MBR start the bootloader'))
s.close()
