#!/usr/bin/env python3
"""bl_launch.py [--dfu] -- start the installed bootloader over SWD, the way the MBR does.

NOTE: the first run ACTIVATES the bootloader. Nordic's main() calls nrf_bootloader_mbr_addrs_populate(), which writes
0xF8000 / 0xFE000 into the MBR page words 0xFF8 / 0xFFC when they are erased (the same words as
`install_bootloader.py --go --activate`). From then on the MBR starts the bootloader on every reset. Undo:
`install_bootloader.py --go --deactivate`.

Resets the chip, halts on the first instruction and does what the MBR does for an activated bootloader (MBR code 0x0A84:
IRQ forwarding word [0x20000000] = 0xF8000, MSP = [0xF8000], PC = [0xF8004]), then lets it run.
  --dfu  also sets GPREGRET = 0xB1 first, like the app's DFU chord: the bootloader stays in DFU mode, advertising as
         "ModelO DFU" (it gives up and resets after 2 minutes without a connection).
  none   the bootloader checks the app against the settings page and starts it (or stays in DFU mode if they do not
         match, or if DPI is held for 2 s).
The bootloader ends a DFU with a reset; because the run activated it, that reset goes MBR -> bootloader, which copies
the received image into place and starts it."""
import sys
import swd

BL = 0xF8000
s = swd.connect(); t = s.target
sp, pc = t.read32(BL), t.read32(BL + 4)
assert sp != 0xFFFFFFFF and 0xF8000 < pc < 0xFE000, 'no bootloader at 0xF8000 (run install_bootloader.py --go)'
swd.stop(t)
t.write32(0x20000000, BL)                 # MBR IRQ forwarding target
if '--dfu' in sys.argv:
    t.write32(0x4000051C, 0xB1)           # POWER.GPREGRET = BOOTLOADER_DFU_START
t.write_core_register('msp', sp)
t.write_core_register('pc', pc & ~1)
t.write_core_register('xpsr', 1 << 24)    # Thumb state
t.resume()
s.close()
print('bootloader started (%s)' % ('DFU mode requested' if '--dfu' in sys.argv else 'normal boot'))
