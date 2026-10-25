# 08 — Debugging a live mouse

## 0. The rules that cost us days

1. **Never halt the CPU while the SoftDevice is running.** A halt stops the SoftDevice's
   timing-critical radio handling; it asserts (error id 1, SD pc around `0x169CE`/`0x187CE`)
   and the app's handler then hits `bkpt @0x284d4` (reloc of orig 0x7474's `bkpt`) or resets.
   Every "crash at 0x284d4" we saw while a debugger was attached was **our own halt**.
   Read memory with the CPU running instead (`tools/probe.py` does).
2. **A debugger attached emulates System OFF**: the chip does not really power down. Judge
   sleep/power with the probe **disconnected**.
3. `pyocd -t nrf52840` fails on ST-Link clones (`Bad AP`). Use `target_override='cortex_m'`
   in Python scripts, or this repo's tools.
4. CFSR is **sticky across resets**. Clear it (`write32 0xE000ED28 0xFFFFFFFF`) before you
   trust it after an experiment. `probe.py status` prints it; both CFSR and HFSR should be 0.
5. One probe user at a time.

## 1. The 10-second health check

```bash
make status
```

Healthy BLE-mode mouse:

```
SD enabled flag [0x20003830]  = 1
vendor mode var [0x20003003]  = 1
CFSR 0x00000000 HFSR 0x00000000
HFCLKSTAT 0x00000001 -> HFXO off          (idle on battery; "RUNNING" while USB is attached)
config page 0xFE000: ['0xc0de0001', '0x1', '0xfffffffe', '0x<generation>']
bond page   0xFD000: magic 0xb0dd0001
LOG+0x004 init stage/err (0x1000 = ok)   = 0x1000
```

| Reading | Meaning |
|---|---|
| `SD flag = 0` in BLE mode | the stub did not bring the SD up; check the stub log (§2) |
| `init stage = 0x100\|n` | `blehid_init` failed at step n (see `blehid.c`: 1 name, 2 appearance, 3 PPCP, 4–14 services/chars, 15 adv configure, 16 adv start) |
| `init stage = 0x2000\|k` | built with `-DSTOP_AT=k` |
| CFSR ≠ 0 | a bus/usage fault; get the PC with a short, *attached-while-faulted* look — but see rule 1 |

## 2. Reading RAM without halting

```bash
python tools/probe.py mem 0x2003F000 0x40     # stub log, see 07-internals §6
python tools/probe.py mem 0x2003F100 0x120    # blehid LOG[]
python tools/probe.py mem 0x200035E5 7        # last stock mouse report buffer (btn, wheel, X, Y, pan)
python tools/probe.py mem 0x20003016 4        # motion accumulators (X, Y)
python tools/probe.py mem 0x20003076 1        # battery %
python tools/probe.py mem 0x20003048 4        # idle seconds counter
python tools/probe.py mem 0x4000040C 4        # HFCLKSTAT  (bit16 = HFXO running, bit0 = source)
```

Stub log words (offset from 0x2003F000): `+4` power_init rc, `+8` sdh_enable rc, `+C` cfg_set
(attr) rc, `+0x10` cfg_set (vs) rc, `+0x14` sd_ble_enable rc, `+0x18` required RAM end, `+0x1C`
blehid_init rc, `+0x24` = `B1E0FFFF` when the stub completed. Any non-zero rc is the Nordic
`NRF_ERROR_*` code (e.g. 4 = NO_MEM: raise the RAM/attr table, 8 = INVALID_STATE).

## 3. Python snippet: a non-halting session

```python
from pyocd.core.helpers import ConnectHelper
s = ConnectHelper.session_with_chosen_probe(options={
    'target_override': 'cortex_m', 'connect_mode': 'attach', 'frequency': 1000000})
s.open(); t = s.target                 # attach WITHOUT halting
print(hex(t.read32(0x20003830)))       # works while the mouse runs
# t.halt()                             # <- do not, unless you will reset afterwards
s.close()
```

Counting how many HID reports the BLE side sent per second (confirms the ~72/s figure):

```python
import time
L = 0x2003F100
a = t.read32(L + 4*0x21); time.sleep(5); b = t.read32(L + 4*0x21)
print((b - a) / 5, 'reports/s')         # while moving the mouse
```

## 4. Disassembling the stock app

```bash
python tools/fdis.py 0xe878 0x20          # disassemble 0x20 bytes at ORIG address 0xE878
python tools/fdis.py x 0x15e5c            # list every BL/B.W that calls 0x15E5C
```

For the relocated, patched image (addresses are **reloc** = orig + 0x21000) use capstone directly:

```python
from capstone import *
img = open('build/golden_app_27000_ble.bin', 'rb').read(); BASE = 0x27000
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
a = 0x35dc8                                   # orig 0x14DC8 (the patched transport call -> MOUSE_T)
for i in md.disasm(img[a - BASE:a - BASE + 0x18], a): print('%x: %s %s' % (i.address, i.mnemonic, i.op_str))
```

The stubs/thunks live outside that file (0x3F000+); disassemble them from the hex with
`IntelHex('build/s140_730_golden27000_ble.hex').tobinstr(start=0x3f800, size=0x180)`.

## 5. Watching the radio side from the host

* Linux: `sudo btmon` shows connect/encryption/connection-update events if you have an adapter.
* Windows: `Get-PnpDevice | ? InstanceId -like '*<MAC>*'` and the scripts in [09](09-test-rig.md).
* In the mouse's `LOG`: index 2 counts BLE events, 3–18 holds the last 16 event ids
  (`BLE_GAP_EVT_*` = 0x10 + n from `fw/sd_api/ble_gap.h`: `0x10` connected, `0x11` disconnected,
  `0x12` conn-param update, `0x13` sec-params request, `0x14` sec-info request, `0x1A` conn-sec
  update, `0x1F` conn-param update request, `0x23`/`0x24` data-length update request/update).
  A repeating `0x10,0x23,0x24,0x14,0x11` = connect → data length → the host asks for the
  encryption key (sec-info request) → disconnect, again and again: the host keeps trying to
  encrypt with a key the mouse no longer has → remove the bond on the host.

## 6. Live-tuning hooks

All are plain RAM words, so you can change behaviour without reflashing.

| What | How |
|---|---|
| Chord masks (mode chord) | `python tools/probe.py chord 0x600 0x1` = BACK(P0.9)+FORWARD(P0.10) on P0, DPI(P1.0) on P1. `chord 0 0` disables. (Masks are active-low input bits; the address is read from the blob's `ENTRY[5]`.) |
| Idle connection parameters | `python tools/probe.py slowconn 12 20 400` (interval 15 ms, latency 20, 4 s timeout) sets `LOG[0x38,0x39,0x3B]` and triggers `LOG[0x3A]`; the next tick asks the host. Try `slowconn 6 0 400` for 7.5 ms. |
| What the host granted | `LOG[0x31]` (interval) and `LOG[0x32]` (latency) after the update event |
| Force an arbitrary RAM write | `python tools/probe.py w32 <addr> <value>` |
| Reset | `python tools/probe.py reset` |

Test ideas that used these: (a) measure interval/latency acceptance by the host
(Windows grants the peripheral's request); (b) poke a low pin mask to test the mode round trip
without pressing three buttons.

## 6b. Faking a chord from the PC

The chords read GPIO input registers. With the mask patched to a pin that is easy to ground
(or to *any* currently-pressed button) you can drive mode switching by software. Example, the
mode toggle round trip using only the left button (P1.15 → mask bit 15 of P1):

```bash
python tools/probe.py chord 0 0x8000    # hold LEFT 3 s → toggles BLE/dongle, mouse resets
python tools/probe.py chord 0x600 0x1   # (after the reset) put the default chord back
```

(The mask is in RAM; it reverts to the compiled default at every reset anyway.)

## 7. Erase the mode or bond record by hand

```bash
python tools/erase_page.py config          # dry run, prints the record
python tools/erase_page.py config --go     # next boot: BLE mode, generation 0
python tools/erase_page.py bond --go       # next boot: unbonded (pairing mode)
```

These are the only two pages that tool may erase (0xFE000 and 0xFD000).

## 8. Bisecting a boot failure

The stub writes a progress log; `blehid_init` writes `LOG[1]`. Typical flow when something
faults after a change:

1. `make status` → read `init stage` and the stub log.
2. Rebuild with `CFLAGS_EXTRA="-DSTOP_AT=<k>"` to cut `blehid_init` at step k; the stage
   markers are the `STOP(n)` lines in `blehid_init`.
3. `NOPOLL=1 python tools/mk_ble.py 720` removes the main-loop hook to separate "init fails"
   from "tick fails".
4. If the **mouse stops enumerating** on USB, a bad stub is likely: reflash the previous
   known-good hex (`backups/…`) with `tools/nvmc_flash.py`.

## 9. Known debugging pitfalls (all hit once)

* Wrong relocated address for a stock function: `orig + 0x21000` and set the Thumb bit
  (orig 0xF9A0 → `0x309A1`, not 0x2F9A1).
* The report buffer is **0x200035E5** (found via USBD EPIN1 `PTR`), not the similar-looking
  0x200032E8 (old buttons/shadow variable). Read the USBD registers to find the real DMA buffer:
  `python tools/probe.py mem 0x40027000 0x700` and look at `EPIN[1].PTR` (0x40027600 + 1×0x14).
* `hvx` before the sys-attrs are restored returns `0x3401` (SYS_ATTR_MISSING); the SD only
  raises the sys-attr request on the first peer ATT request. The module sets
  `S.notify_on=1` in the restore path so the idle policy works after a bonded reconnect.
* Idle slow-params did "never fire" because `notify_on` was not set on a bonded reconnect.
  Fixed; keep it in mind if you refactor the sys-attr code.
