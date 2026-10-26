#!/usr/bin/env python3
"""watch.py [seconds] [--quiet] -- NON-HALTING monitor for regression runs: prints an event line whenever something changes
and a summary at the end. Never halts the CPU, only clears the stub's "boot finished" marker (0x2003F024).
Events: REBOOT (stub finished again, or RTC1 counter went backwards), FAULT (CFSR/HFSR != 0), SD flag change, mode-var
change, BLE connect/disconnect (S.conn), USB attach/detach, motion/buttons (report buffer), LED duty change, DPI/settings
page rewrite (flash 0x8B000/0x8C000 content hash), bond/config page change.
Exit code 0 = no reboot and no fault during the run, 1 = otherwise."""
import sys, time, zlib
from pyocd.core.helpers import ConnectHelper
secs = float(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else 60
s = ConnectHelper.session_with_chosen_probe(options={'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target
r32, r8 = t.read32, t.read8
DONE = 0x2003F024
t.write32(DONE, 0)
t0 = time.time(); ev = []
def log(msg):
    ev.append((time.time() - t0, msg)); print('%6.1fs  %s' % (time.time() - t0, msg), flush=True)
def snap():
    return dict(sd=r8(0x20003830), mode=r8(0x20003003), usb=r8(0x200035DE), conn=t.read16(0x2000B400),
                led=tuple(t.read_memory_block8(0x20003270, 6)), cfsr=r32(0xE000ED28), hfsr=r32(0xE000ED2C),
                set1=zlib.crc32(bytes(t.read_memory_block8(0x8B000, 0x1000))), set2=zlib.crc32(bytes(t.read_memory_block8(0x8C000, 0x1000))),
                bond=zlib.crc32(bytes(t.read_memory_block8(0xFD000, 64))), cfg=tuple(t.read_memory_block32(0xFE000, 4)))
prev = snap(); log('start ' + ', '.join('%s=%s' % (k, v) for k, v in prev.items() if k in ('sd', 'mode', 'usb', 'conn')))
last_rtc = r32(0x40011504); reboots = faults = 0; rep0 = bytes(t.read_memory_block8(0x200035E5, 7))
while time.time() - t0 < secs:
    time.sleep(0.2)
    try:
        if r32(DONE) == 0xB1E0FFFF:
            reboots += 1; log('REBOOT (stub finished again)'); t.write32(DONE, 0)
        rtc = r32(0x40011504)
        if ((last_rtc - rtc) & 0xFFFFFF) < 0x800000 and last_rtc - rtc > 32768 and not (last_rtc > 0xF00000): log('RTC went backwards (reset?)')
        last_rtc = rtc
        cur = snap()
    except Exception as e:
        log('probe error: %s' % e); continue
    for k in cur:
        if cur[k] != prev[k]:
            if k in ('cfsr', 'hfsr'):
                if cur[k]: faults += 1; log('FAULT %s=0x%08x' % (k.upper(), cur[k]))
            elif k == 'led': pass
            else: log('%s: %s -> %s' % (k, prev[k], cur[k]))
    if cur['led'] != prev['led'] and '--quiet' not in sys.argv: log('led duty %s' % (cur['led'],))
    rep = bytes(t.read_memory_block8(0x200035E5, 7))
    if rep != rep0 and '--quiet' not in sys.argv: log('report buffer %s' % rep.hex(' ')); rep0 = rep
    prev = cur
log('end: %d reboot(s), %d fault event(s), %d events' % (reboots, faults, len(ev)))
s.close(); sys.exit(1 if reboots or faults else 0)
