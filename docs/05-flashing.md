# 05 — Flashing

Precondition: [03-backup-restore](03-backup-restore.md) done and verified.

## 1. First install (stock chip → SoftDevice + BLE firmware)

```bash
make dry-run                 # optional but recommended: shows what will change
make flash-first             # = python tools/nvmc_flash.py build/…_ble.hex --go --include-sd
```

Expected output (abridged):

```
image pages 0x0 .. 0x41fff 66 pages
pages to rewrite: ['0x0', '0x1000', …, '0x41000']
page 0x0 verify OK
page 0x1000 verify OK
…
flashed + reset
```

It takes about a minute. What happens on the mouse: the MBR is installed, the SoftDevice,
the relocated app and BLE module are written, the chip resets, the stub finds no config
record (0xFE000 erased) and **defaults to BLE**.

> The `--include-sd` path was verified here only as a **dry run** against a chip that already
> carried the same image (and as a dry run against the original backup). The original
> SoftDevice install in this project went through `pyocd flash -t nrf52840 -f 200k` with a
> CMSIS-DAP probe. If you want the battle-tested route and have such a probe, use it:
>
> ```bash
> pyocd flash -t nrf52840 -f 200k build/s140_730_golden27000_ble.hex
> pyocd reset -t nrf52840
> ```
> Both routes only write addresses inside the hex (no UICR). Both leave 0x8B000/0x8C000 and
> 0xFD000/0xFE000 alone.

## 2. Normal update (everything already installed)

```bash
make build && make flash          # writes only differing pages inside 0x27000..0xFD000
```

## 3. Wake-up and first look

1. The LED blinks **blue twice**, or **purple twice** when no host is bonded (= pairing mode).
2. Detach the probe or at least do not halt the CPU (see [08](08-debugging.md)).
3. Health check without halting:

   ```bash
   make status
   # SD enabled flag [0x20003830]  = 1
   # vendor mode var [0x20003003]  = 1
   # CFSR 0x00000000 HFSR 0x00000000
   # LOG+0x004 init stage/err (0x1000 = ok)   = 0x1000
   ```
4. Pair it on your host ([06 §4](06-user-guide.md#4-pairing)). Move the mouse.

## 4. Flash by hand without the Makefile (what `nvmc_flash.py` does)

If you need to understand or port it: the script halts the core, then for each 4 KB page that
differs (halting a running SoftDevice makes it assert, which is harmless here because the
script ends with a reset):

```
NVMC.CONFIG (0x4001E504) = 2       # erase enable
NVMC.ERASEPAGE (0x4001E508) = page # wait NVMC.READY (0x4001E400)
NVMC.CONFIG = 1                    # write enable
write each non-0xFFFFFFFF word, wait READY
NVMC.CONFIG = 0
read back + compare                # assertion failure on mismatch
AIRCR (0xE000ED0C) = 0x05FA0004    # SYSRESETREQ
```

## 5. After flashing: things that bite

* **Windows keeps a bond for the old identity.** After you re-flash with a *different
  encryption key set* (e.g. you erased the bond page, or ran a force re-pair), remove the
  device in Windows before pairing again, otherwise Windows retries encryption forever
  (symptom: BLE event loop `0x10,0x23,0x24,0x14,0x11` in `LOG`). See
  [06 §4](06-user-guide.md#4-pairing).
* A **normal `make flash` keeps the bond** (page 0xFD000), so Windows reconnects by itself.
* Debugger attached ⇒ **System OFF is only emulated** and halting breaks the SoftDevice.
  Judge sleep/power and real behaviour with the probe disconnected.
* A flat battery looks like "mouse is dead / not enumerating".
