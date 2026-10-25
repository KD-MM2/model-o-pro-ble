# 12 — Plan: update over USB (custom copier bootloader)  — NOT STARTED

Status: **proposal, nothing built.** Goal: after one SWD install, update the app/BLE module
(0x27000–0x42000) over USB with no probe. Why the vendor tool cannot do it: see
[11](11-history-and-next.md) and the chat history (it can only write 0x6000–0x1CC8F through a
bootloader that no longer exists on this unit).

## Design

* **App receives, a tiny bootloader copies.** The stock app already has a USB stack and the vendor
  HID channel used by Glorious CORE; reuse it (do not write a USB stack).
* App-side vendor commands (new): `begin`, `chunk`, `end(CRC32)`, `reboot-to-copier`. Chunks are
  written to a staging area at **0x80000** through the SoftDevice flash API (the path that already
  works for the DPI settings).
* Copier bootloader (~1 KB, no USB, runs before the SoftDevice so it may use NVMC directly):
  validate the staging header (magic, length, CRC32) → erase + copy to 0x27000.. → clear the
  header → jump to the MBR/SoftDevice (0x1000). A power cut mid-copy leaves the staged image intact;
  the next boot repeats the copy.
* Host tool (Python + hidapi): sends frames with retries, verifies by readback, dry-run mode,
  refuses wrong size/magic. Cannot emulate the vendor tool (it expects PID 258A:2100).
* Scope: app + blehid only. MBR/SoftDevice stay fixed (SWD only). Stock settings (DPI, LED, remaps)
  already work over USB via Glorious CORE; BLE settings (idle timeout, mode, re-pair) would be new
  vendor commands in the same channel.

## Layout change required

| Region | Now | Planned |
|---|---|---|
| copier | – | 0xF4000 (`UICR.BOOTLOADERADDR`) |
| bond record | 0xFD000 | move (e.g. 0xF0000) — 0xFD000/0xFE000 clash with MBR param / bootloader settings pages |
| config record | 0xFE000 | move (e.g. 0xF1000) |
| staging | – | 0x80000.. (unused) |
| app limit | 0xFD000 | 0xF0000; update `nvmc_flash.py` HI and the erase/restore docs |

`blehid.c` should read the old pages once so existing bonds/mode survive the move.

## Phases (each testable and reversible)

0. Fresh tagged full dump; write the layout into the docs.
1. Move records; write the copier; test it **without UICR** by starting it from SWD with a
   hand-staged image, including a "power cut mid-copy" test. Inert until UICR is written, so it
   cannot brick anything.
2. App-side USB commands (hook the stock vendor HID handler); CRC check before the reset hand-off.
3. Host tool.
4. **Only with explicit owner approval:** write `UICR.BOOTLOADERADDR = 0xF4000` once over SWD
   (single word, no erase, leaves APPROTECT alone; breaks the "never flash UICR" rule, undone only by
   a UICR erase). Then end-to-end USB update with the probe unplugged, plus failure tests
   (cable pulled mid-transfer, mid-copy).

## Risks

* Copier bug: only live after step 4 — hence thorough step 1.
* A bad but CRC-valid app: copier cannot know; optional mitigation = keep the previous image and
  add a "revert" command. Otherwise SWD recovers.
* Bad copier after UICR is set: SWD recovers (needs the probe).
