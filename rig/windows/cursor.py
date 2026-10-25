import ctypes, time, sys
from ctypes import wintypes
pt = wintypes.POINT()
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20
t0 = time.time(); last = None; moves = 0
print('start', flush=True)
while time.time() - t0 < secs:
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    cur = (pt.x, pt.y)
    if cur != last:
        moves += 1
        if moves < 40: print(round(time.time()-t0, 2), cur, flush=True)
        last = cur
    time.sleep(0.02)
print('cursor changes', moves)
