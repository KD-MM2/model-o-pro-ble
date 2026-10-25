import ctypes, time, sys
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
u = ctypes.windll.user32
names = {1: 'LEFT', 2: 'RIGHT', 4: 'MIDDLE', 5: 'X1(back)', 6: 'X2(fwd)'}
t0 = time.time(); last = {}
print('start', flush=True)
while time.time() - t0 < secs:
    for vk, n in names.items():
        d = bool(u.GetAsyncKeyState(vk) & 0x8000)
        if last.get(vk) != d:
            print(round(time.time() - t0, 2), n, 'DOWN' if d else 'up', flush=True)
            last[vk] = d
    time.sleep(0.01)
print('done', flush=True)
