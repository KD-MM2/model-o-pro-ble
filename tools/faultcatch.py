#!/usr/bin/env python3
"""faultcatch.py [seconds] -- catch a real Cortex-M fault with a hardware breakpoint on the app's fault-handler spin loops
(the stock vectors NMI/HardFault/MemManage/BusFault/UsageFault all point at `b .`). Those addresses are only reached
on a genuine fault, so halting there is safe (the system is already dead; the watchdog would reset it anyway).
On a hit it prints the fault registers, the stacked frame (faulting PC/LR), a disassembly around the faulting PC in the
STOCK image (orig = reloc - 0x21000), a crude backtrace from the stack, saves everything to build/faultcatch.txt, then
resets the chip. Run it, then reproduce the problem."""
import sys, time, struct
from pyocd.core.helpers import ConnectHelper
from capstone import *
D = 0x21000
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 300
stock = open('stock/golden_app.bin', 'rb').read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS | CS_MODE_V8)
def dis(orig_addr, before=0x20, after=0x20):
    out = []
    for i in md.disasm(stock[orig_addr - 0x6000 - before: orig_addr - 0x6000 + after], orig_addr - before):
        out.append('%s%x: %s %s' % ('>>' if i.address == orig_addr else '  ', i.address, i.mnemonic, i.op_str))
    return out
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
vec = [t.read32(0x27000 + 4 * n) & ~1 for n in (2, 3, 4, 5, 6)]
names = dict(zip(vec, ('NMI', 'HardFault', 'MemManage', 'BusFault', 'UsageFault')))
HANDLER_BKPT = 0x74d4 + D     # `bkpt` inside the app's error handler app_error_fault_handler(id, pc, info) (orig 0x7474)
vec.append(HANDLER_BKPT); names[HANDLER_BKPT] = 'app_error_fault_handler bkpt'
for a in set(vec): t.set_breakpoint(a)
print('armed on', {hex(a): n for a, n in names.items()}, 'for', secs, 's -- reproduce now', flush=True)
t0 = time.time(); hit = False
while time.time() - t0 < secs:
    time.sleep(0.1)
    try:
        if t.is_halted(): hit = True; break
    except Exception: pass
rep = []
if hit:
    pc = t.read_core_register('pc'); lr = t.read_core_register('lr')
    msp = t.read_core_register('msp'); psp = t.read_core_register('psp')
    R = [t.read_core_register('r%d' % i) for i in range(13)]
    rep.append('HALT at %.1fs: %s (pc 0x%x)' % (time.time() - t0, names.get(pc & ~1, '?'), pc))
    rep.append('CFSR 0x%08x HFSR 0x%08x DFSR 0x%08x' % tuple(t.read32(a) for a in (0xE000ED28, 0xE000ED2C, 0xE000ED30)))
    rep.append('r0-r12: ' + ' '.join('%08x' % x for x in R))
    rep.append('lr 0x%08x msp 0x%08x psp 0x%08x ipsr %d' % (lr, msp, psp, t.read_core_register('xpsr') & 0x1FF))
    if (pc & ~1) == HANDLER_BKPT:
        rep.append('app_error_fault_handler(id=0x%x, pc=0x%x, info=0x%x)   [id 1 = SoftDevice assert, 0x1001 = APP_MEMACC, 0x4001 = app memory access fault]' % (R[0], R[1], R[2]))
        for lab, a in (('handler arg pc', R[1]),):
            o = (a & ~1) - D
            if 0x6000 <= o < 0x1CC90: rep.append('%s = reloc 0x%x = orig 0x%x:' % (lab, a & ~1, o)); rep += dis(o)
            else: rep.append('%s 0x%x is outside the relocated app (SoftDevice region if < 0x27000)' % (lab, a))
    for lab, a in (('lr', lr),):
        o = (a & ~1) - D
        if 0x6000 <= o < 0x1CC90: rep.append('%s = reloc 0x%x = orig 0x%x:' % (lab, a & ~1, o)); rep += dis(o)
    for nm, sp in (('MSP', msp), ('PSP', psp)):
        if 0x20000000 <= sp < 0x20040000:
            st = t.read_memory_block32(sp, 96); bt = []
            for i, w in enumerate(st):
                if w & 1 and 0x27000 <= w < 0x42000 and (w & ~1) - D >= 0x6000: bt.append('  %s+0x%x: 0x%x (orig 0x%x)' % (nm, 4 * i, w, w - D))
            rep.append('%s return-address-like words (call chain, nearest first):' % nm); rep += bt[:14]
else:
    rep.append('no fault within %.0f s' % secs)
txt = '\n'.join(rep); print(txt)
open('build/faultcatch.txt', 'w').write(txt + '\n')
for a in set(vec): t.remove_breakpoint(a)
if hit: t.write32(0xE000ED0C, 0x05FA0004); time.sleep(0.3); print('chip reset')
s.close()
