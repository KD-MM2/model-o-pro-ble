# 09 — The Windows BLE test rig

Optional, but it is how every BLE behaviour in this project was verified. The rig is a Windows
11 PC (with a BLE adapter) driven from the Linux dev machine over `ssh`. Pure-Python (`bleak`)
and Win32 calls; nothing is installed on the mouse.

## 1. Why a scheduled task?

Windows refuses BLE pairing/GATT operations from an **ssh session** (`ACCESS_DENIED`). They only
work from the logged-in **interactive desktop session**. So each script is started as a one-shot
scheduled task with `/IT` (interactive), and its output is redirected to a file that is read
back over ssh.

```
Linux ──ssh──> Windows:  schtasks /Create … /RU <user> /IT   then   schtasks /Run
                         run_task.cmd <script.py> args  →  %USERPROFILE%\out_<script>.txt
Linux ──ssh──> type %USERPROFILE%\out_<script>.txt
```

## 2. One-time Windows setup

1. Enable OpenSSH Server, log in to the desktop as the test user (the task needs that session).
2. Python 3.10+; create the venv and install bleak:

   ```powershell
   py -3 -m venv %USERPROFILE%\blevenv
   %USERPROFILE%\blevenv\Scripts\pip install bleak
   ```
3. Copy `rig/windows/*` (the `.py`, `.ps1`, `run_task.cmd`) to `%USERPROFILE%`.
4. On Linux add an ssh alias (`~/.ssh/config`) for the Windows host.
5. Find the mouse's BLE address:

   ```bash
   export WIN_HOST=g15 WIN_USER=<windows user>
   ssh $WIN_HOST "%USERPROFILE%\blevenv\Scripts\python %USERPROFILE%\ble_scan.py 'Model O' 10"
   #   (scanning may also work from plain ssh; if it returns nothing, run it through run_task.cmd like the others)
   # D6:BF:B2:D9:43:F2 'Model O PRO Wireless' rssi -52 uuids ['00001812-…']
   export MOUSE_MAC=D6BFB2D943F2        # 12 hex digits, no colons
   ```
   The address **changes after "force re-pair"** (the pairing generation is part of it).

## 3. Commands (`rig/windows/winctl.sh`)

```bash
export WIN_HOST=g15 WIN_USER=<user> MOUSE_MAC=<12hex>
rig/windows/winctl.sh clean              # remove stale PnP nodes of the mouse (pnputil)
rig/windows/winctl.sh unpair             # bleak unpair (waits 20 s, prints result)
rig/windows/winctl.sh pair               # scan, connect, pair (Just Works), list GATT services
rig/windows/winctl.sh cursor 12          # log cursor position changes for 12 s  (move the mouse!)
rig/windows/winctl.sh cursorout          # read the result
rig/windows/winctl.sh battery            # read BAS 0x2A19
rig/windows/winctl.sh btnwatch 60        # log button down/up (L, R, M, back, fwd) for 60 s
rig/windows/winctl.sh btnout
```

## 4. A full verification session (what we ran)

```bash
# fresh identity (after flashing a new bond / force re-pair)
winctl.sh unpair; winctl.sh clean; winctl.sh pair
#   expect: "pair result True", services DIS/BAS/HID listed, battery char value
winctl.sh cursor 12 && <move the mouse for 12 s> && winctl.sh cursorout
#   expect: "cursor changes N" with N in the hundreds
winctl.sh btnwatch 30 && <click every button, spin the wheel> && winctl.sh btnout
winctl.sh battery
# on the mouse side, during/after:
make status                     # LOG+0x080 hvx result 0, LOG+0x084 reports sent counting up
python tools/probe.py mem 0x2003F1C0 0x10   # conn interval 6 (=7.5 ms), after update; latency
```

Reference numbers from the verified run: 1883 reports in 26 s (~72/s), last `hvx` result 0,
564 cursor position changes in the sampling window, connection interval 6 (7.5 ms), CFSR 0.

## 5. The scripts

| Script | What it does |
|---|---|
| `ble_scan.py [name] [secs]` | active scan, prints address/name/RSSI/UUIDs |
| `ble_pair.py [name]` | find by name, connect, `pair()`, enumerate services/characteristics, read what is readable |
| `ble_unpair.py [MAC]` | connect (best effort) and `unpair()` |
| `ble_battery.py [MAC]` | read Battery Level over GATT |
| `cursor.py [secs]` | poll `GetCursorPos`, print each change (counts moves) |
| `btnwatch.py [secs]` | poll `GetAsyncKeyState` for buttons 1,2,4,5,6 |
| `battery.ps1 [-Mac …]` | PnP view of the device's properties (battery property key `…104EA319…`) |

## 6. Windows-specific behaviours we met

* **Stale bond after a key change** → Windows connects, requests encryption forever (see
  [08 §5](08-debugging.md#5-watching-the-radio-side-from-the-host)). Cure: `unpair`, `clean`, pair again.
* After **flashing the app only** (same bond page) no re-pair is needed: Windows reconnects by
  itself, re-encrypts with the stored LTK and the module restores the CCCD with
  `sd_ble_gatts_sys_attr_set`, then reports flow.
* Windows **ignores PPCP** and keeps its own connection interval; the module therefore asks
  explicitly for 7.5 ms once connected/encrypted (and again on the first report after an idle
  period). Windows accepts it.
* A **stuck key** seen once was Windows Explorer's problem (Ctrl-Alt-Del → exit fixed it), not
  the mouse. Switching hosts used to leave "pressed" state on the old host; the module now sends a
  neutral report and disconnects cleanly when it leaves a link (mode switch, USB take-over,
  sleep).
