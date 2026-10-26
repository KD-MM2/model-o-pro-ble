# 03 — Backup, restore, recovery (read this first)

SWD is the master key: as long as the probe can connect, nothing here can brick the mouse.
A **full flash image** is the restore point.

## 1. Back up (read-only, safe at any time)

```bash
source .venv/bin/activate
make backup                      # -> backups/<YYYY-MM-DD-HHMM>/{full_flash_1MB.bin, uicr.bin, SHA256SUMS}
# or explicitly:
python tools/dump_flash.py backups/2026-10-26-before-ble
(cd backups/2026-10-26-before-ble && sha256sum -c SHA256SUMS)
```

It takes ~17 s with an ST-Link, prints `APPROTECT (UICR 0x10001208) = 0x…` (0xFFFFFFFF = open)
and never writes. Keep **two copies**, one outside the repo (`backups/` is git-ignored on
purpose: the dump contains the vendor firmware).

What a good "before" dump of a mouse that runs the stock app looks like:

| Region | Content |
|---|---|
| 0x0000 | 16-byte stub (initial SP + reset vector → next stub) on this unit; a factory unit has MBR + vendor bootloader instead |
| 0x6000–0x1CC8F | the stock app, reset vector `0x000063DD`, initial SP `0x2000AF50` |
| 0x8B000, 0x8C000 | vendor settings (DPI, LED, button map…), ~550 B and ~1 KB |

Sanity-check the dump before relying on it:

```bash
python tools/extract_stock.py backups/<date>/full_flash_1MB.bin
# initial SP 0x2000af50  reset vector 0x000063dd
# stock/golden_app.bin  sha256 18f8b30a…   (v1.00.00, 2022-08-10)
```

`extract_stock.py` refuses to write if the vector table is not a plausible 0x6000 app (so it
correctly fails on a chip that already carries the SoftDevice).

## 2. What the flasher can and cannot touch

`tools/nvmc_flash.py` is deliberately restrictive:

| Option | Region written |
|---|---|
| (default) | 0x27000 – 0xFCFFF only (the app, our blobs) |
| `--include-sd` | 0x00000 – 0xFCFFF (adds MBR + SoftDevice) |
| never | 0xFD000+ (bond & mode records), UICR, anything ≥ 0xFD000 |

It works page by page: it reads each 4 KB page, rewrites only pages whose image bytes differ
(erase → write words → verify), then issues `SYSRESETREQ`. **No `--go` = dry run**, which only
lists the pages that *would* change. Always dry-run first.

## 3. Restore the original (pre-BLE) state

```bash
# dry run: lists every page that differs from the backup
python tools/nvmc_flash.py backups/<date>/full_flash_1MB.bin --include-sd
# do it
python tools/nvmc_flash.py backups/<date>/full_flash_1MB.bin --include-sd --go
```

(The `.bin` is loaded at base 0; use `--base 0x…` for partial images.) This was dry-run
tested against the original backup; the pages 0x0–0x41000 and 0x8B000 differ from a BLE-running
unit, as expected (0x8B000 is the vendor settings page the stock firmware rewrites when you
change DPI etc.).

With a **CMSIS-DAP probe** the classic way also works:

```bash
pyocd flash -t nrf52840 -f 200k --base-address 0x0 backups/<date>/full_flash_1MB.bin
```

Do **not** use `--erase chip`: it clears UICR and, on newer silicon, can re-lock the debug port.

After a restore the stock firmware runs again (the backup contains its two boot stubs);
the SoftDevice is gone. The bond (0xFD000) and mode (0xFE000) pages are untouched by the
restore, and the stock app ignores them.

## 4. Return to the BLE firmware from a restore

```bash
make flash-first
```

## 5. Recovery cases

| Situation | Fix |
|---|---|
| Flashed a bad app, mouse does nothing | Probe still works → restore (§3). SWD is independent of the app. |
| `pyocd` cannot connect | Check wiring/series resistors, power the mouse by its own USB, try `-f 100k`/`-f 200k`, replug the probe. |
| `Bad AP` with `-t nrf52840` (ST-Link) | Use this repo's tools (`cortex_m` target) — see [02](02-prerequisites.md#3-check-the-probe-sees-the-chip-read-only). |
| BLE bond lost / Windows keeps failing to encrypt | `Left+Right+DPI` held 3 s forces a clean re-pair; remove the old device in Windows first ([06](06-user-guide.md#4-pairing)). |
| Mouse stuck in the other mode | Hold the mode chord (DPI+Back+Forward, 3 s), or erase the config page 0xFE000 (see [08](08-debugging.md#7-erase-the-mode-or-bond-record-by-hand)). |
| Chip reports APPROTECT enabled | Only `ERASEALL` unlocks it; that wipes everything. Restore from the dump afterwards (`--include-sd`); the vendor bootloader cannot come back. |

## 5. Backups made during this project (for reference)

| Backup | What it was |
|---|---|
| `2026-10-25-working/` | stock app + two bench stubs, "everything works" — the ultimate restore point |
| `2026-10-25-ble-stable{,-v2,-v3}` | BLE firmware checkpoints (hex, source, flasher, flash dump) |
| `2026-10-26-ble-stable-v4-power/` | current: BLE + all power optimisations |

These live in the original working tree (`../_backups/`), not in this repo.
