# Report — Running the Model O Pro app on top of Nordic MBR + S140 7.3.0

Date: 2026-10-25. Target: Glorious Model O Pro Wireless (nRF52840). All work under `work/`.
Result: **MBR + S140 7.3.0 + the vendor app relocated from 0x6000 to 0x27000 boots, the mouse enumerates over USB (258A:2015, keyboard + mouse hidraw), CFSR = 0, and it re-enumerates after an SWD reset.** The SoftDevice is present but not enabled yet (flag byte 0x20003830 = 0). BLE itself is not working yet.

Not verified: cursor motion and buttons were not exercised, only enumeration and fault state. The dongle/2.4 GHz link, the CLI and every BLE path were not exercised.

---

## 1. Starting point

- The mouse ran the stock vendor app (`golden_app.bin`, flash 0x6000–0x1CC8F, 93 328 B) via two hand-made stubs (16 B at 0x0 and 0x1000). No bootloader, MBR or SoftDevice on the chip.
- Earlier analysis (other agent's `output/S140-STUDY.md`, and `HANDOFF*.md`):
  - The app's 39 distinct SVC numbers all match the official S140 6.x/7.x ABI, so the app is a SoftDevice-first SDK 17.x build in which BLE was dormant.
  - The app never calls `sd_ble_enable` (0x60) or `sd_ble_cfg_set` (0x69) and never sets the vector-table base (0x13).
  - S140 7.3.0 occupies 0x1000–0x26497, so the app cannot stay at 0x6000. It has to be relocated to ≥ 0x27000.
- Constraints: only SWD, never `--erase chip`, never flash UICR, keep the vendor config pages at 0x8B000/0x8C000, one probe user at a time. Restore path: `_backups/2026-10-25-working/full_flash_1MB.bin`.
- Probe check: UICR APPROTECT reads 0xFFFFFFFF (not the 0x5A the first handoff expected). SWD connects fine, so this is "open" on this silicon.

## 2. Approach

The job is a **binary relocation of a flat Cortex-M image** (base 0x6000 → 0x27000, delta D = +0x21000), done without source or relocation records.

- PC-relative encodings (B/BL/B.W/CBZ/ADR/LDR-literal) move with the image and need nothing.
- **Absolute words** (vector table entries, literal-pool pointers, data-table pointers) must each get +D.
- Words that merely look like addresses (string tails, instruction halfwords, constants) must **not** be patched.
- RAM-init data that contains flash pointers has to be patched too.

Tools (all in `work/`): `relocate.py` (patcher), `unpack.py` (init-blob decoder), `equiv.py` (Unicorn equivalence test), `mkhex.py` (image assembly), plus the hardware debug scripts listed in §6.

## 3. Building the relocator

### 3.1 Starting patch list and why it was not enough
The other agent's scanner (`rebase_scan.py`) reported 124 must-change words and 696 "ambiguous" in-image words. I used its output as a start and found:

1. **The scanner mis-decodes literal pools as code.** Example: the pool at 0x64CC/0x64D0 holds the INIT-table bounds (0x1C710/0x1C730); it was missed. About 20 pointers were found this way.
2. **Many "ambiguous" words are not pointers.** Examples:
   - `"%s\0\0"`, `".c\0\0"` string tails (value 0x7325, 0x632E);
   - `pop {...,pc}`/`b .` halfword + zero padding (values 0xBD10, 0xBD70, 0xE7xx, …);
   - constants (0xFFFF, CRC poly 0x11021, key tables 0x8200–0x8403, the bss length 0x76A8).
3. Some words that look like strings *are* pointers (vector table entries, `0x7340` → the string "Driver\\app_ble.c", `0x7475` → `app_error_fault_handler`).

### 3.2 The RAM-init blob (important and easy to miss)
- The startup table at 0x1C710 has two entries `{src, dst, len, fn}`.
- Entry 0: src 0x1C944, dst RAM 0x20003000, len 0x8A8, fn 0x64D4 = an **IAR packbits-style decompressor**. Decoding it (see the format below) shows the blob holds flash pointers: HID report descriptor table, strings, device name, observer tables, function pointers (0x8361, 0x13D5B).
- Entry 1 (src 0x1CC90, len 0x76A8, fn 0x7210) is the `.bss` clear, **not** 30 KB of code. Its src is unused. (Handoff 1's "missing blob" concern is moot.)
- Packbits format (read off the routine at 0x64D4): token `t`; `lit = t&7` (0 → next byte); `z = t>>4` (0 → next byte); copy `lit-1` literal bytes; if `t&8`, copy `z+2` bytes from `dst-offset` (offset is the next byte), else write `z` zero bytes.
- `relocate.py` decodes the blob, adds D to the 24 flash-pointer words (list `RAMP`), and re-packs with literal-only tokens (2.2 KB instead of 844 B). The table src stays at the same relative address; entry 1's src is pointed at the new image end.

### 3.3 Final patch rules (`relocate.py`)
Patch set = scanner must-change (vectors + pool) ∪ filtered ambiguous words ∪ a second sweep of every aligned in-range word, minus false positives:
- words below 0x10000 whose bytes are both printable ASCII → string, skip (except explicit real pointers);
- instruction-halfword-plus-padding patterns → skip;
- known constants → skip;
- words below 0x10000 inside code (0x6100–0x1A000) must have an LDR-literal loader (16-bit and `ldr.w`), otherwise skip;
- second sweep: any other aligned word with value ≥ 0x10000 in range → patch (data pointers), except 0x11021;
- an explicit `REAL` / `EXTRA_REAL` list of individually verified pointers (see §5).

Final count: 584 patched words in flash (+24 in the RAM-init blob), 210 excluded.

### 3.4 Image assembly
`mkhex.py` merges the official `s140_nrf52_7.3.0_softdevice.hex` (MBR 0x0–0xB00 + SD 0x1000–0x26497, sha 5f460d35…, no UICR records) with the relocated app at 0x27000. Output: `out/s140_730_golden27000.hex` (0x0–0x3E206). I checked the app bytes read back from the hex equal `golden_app_27000.bin`.

Layout needs no further change: the SD reserves RAM below 0x20003000 and the app already links at ≥ 0x20003000; the SD forwards interrupts to the app vector table at 0x27000 by default (the app never writes VTOR, so no `svc 0x13` is needed while the SD is not enabled).

## 4. Host-side verification (Unicorn)

`equiv.py` runs the original (0x6000) and relocated (0x27000) images and compares PC traces (minus D; the decompress routine is excluded because my repacking changes its path) and RAM at 0x20003000..:
- Peripheral hacks: HFCLK/LFCLK started events set on task writes, polled event registers released after 16 reads.
- Result: 8M instructions, 2222 unique PCs, identical traces; all RAM differences are exactly +0x21000 on pointer words.
- Limit: this proves only paths the emulator reaches (init). It never ran the IRQ, USB or timer paths, which is where all later bugs were.
- Along the way Unicorn did catch one real miss: 0x1B010 = 0x7D65 (a function pointer sitting in a string-looking region).

## 5. Hardware bring-up — what failed and why

Flash command: `pyocd flash -t nrf52840 -f 200k out/s140_730_golden27000.hex`, then reset.
(A coordination slip: the other agent flashed their canary at the same time; their later flash overwrote 0x27000. After the user paused them I reflashed.)

| # | Symptom | Debug method | Root cause | Fix |
|---|---|---|---|---|
| 1 | HardFault at `b .` 0x273E6, INVSTATE, PC=0x3D730 in the POWER_CLOCK ISR | IRQ0 breakpoint + single-step with SP column (`trace_irq.py`) | The scanner had claimed the word at 0x124F0 as a pool pointer, but it is `pop {r4,r5,r6,pc}` + padding. Adding D turned it into garbage, leaving SP 8 bytes off, so the ISR popped a wrong LR | Words < 0x10000 in code need an LDR-literal loader (then 0x124F0 was left alone) |
| 2 | USBD enabled, host starts enumerating, then HardFault (pc=0, lr=0x39EF5) | Fault frame at MSP; mapped lr to the app-timer list code at 0x18EC0 | A callback pointer (0xE1BD) never relocated; it sat next to a data pointer with no detectable loader | Added 0xE19C=0xE1BD to `EXTRA_REAL` |
| 3 | (found by flashing a **stub-only** build, no SD) a RAM cell 0x20003700 = **0x8725** | read RAM after run | 0x1AFD0=0x8725 is the USB-power event handler pointer inside a config struct, excluded by me as a constant. In the stub build it "worked" because the old 0x6000 area still held S140 bytes; with the real image it jumped into SoftDevice code | Added to `EXTRA_REAL`; also **removed** the wrong patches of the key constants 0x8201/0x8401/0x8403 |
| 4 | CLI command table entries | table dump | 0xF3A9, 0xF3D3, 0xF341, 0xF3FD (function pointers in a table whose neighbours were patched) had been dropped by the instruction-tail filter | added to `EXTRA_REAL` |

Isolation trick that helped: a stub-only image (`out/stub_golden27000.hex`: 32-byte stub at 0 that sets VTOR=0x27000 and jumps to the app, no S140 in the boot path) separated "relocation bug" from "SoftDevice interaction". It also hid bug #3 (see above), so it is a necessary but not sufficient test: run the relocated app on the real SD build, or erase the old 0x6000–0x26FFF area first.

Final result on the SD build: `lsusb` shows 258a:2015; dmesg shows both HID interfaces; CFSR=0, HFSR=0; PC in thread mode; USBD enabled; reset → re-enumerates.

## 6. Debug tooling (reusable)

- `trace3.py / trace3b.py / trace3c.py` — reset, break on the IRQ0 handler, single-step N instructions printing PC (+ LR/SP).
- `st.py` — one-shot state: PC/LR/SP/xPSR, CFSR/HFSR, USBD enable, POWER events/INTEN, NVIC.
- `fr.py` — read the stacked exception frame at MSP (at the `b .` HardFault handler, MSP points at it).
- `wp.py` — DWT write watchpoints (found who writes INTENSET).
- `ev.py`, `crash.py`, `stk.py` — smaller helpers. Note: `pyocd cmd` connects without halting by default; use `connect_mode='attach'`/explicit `halt` in scripts. Avoid `pkill -f <script>` from a shell whose command line contains the name (it killed my own shell once).

## 7. Open risks / what is not proven

1. ~380 words in the old address range remain unpatched in the image; they are believed to be instruction halves, string tails and constants, but only paths run so far are proven (boot, POWER_CLOCK ISR, USB enumeration, the app-timer list).
2. Untested: dongle/2.4 GHz mode, buttons/cursor under load, CLI, bonding/pairing store use, sleep paths (`sd_power_system_off` is an SVC and now becomes a real SD call).
3. The SoftDevice is idle. Nothing yet calls `sd_softdevice_enable`/`sd_ble_cfg_set`/`sd_ble_enable`.

## 8. Next steps (BLE)

1. Boot hook: call `nrf_sdh_enable_request` (relocated address 0x32C18), then `sd_ble_cfg_set` (svc 0x69) and `sd_ble_enable` (svc 0x60) with the RAM start the SD asks for (default app RAM at 0x20003000 only fits default config), then the dormant advertising controller (rebased 0x29F00/0x29F10) and set the flag 0x20003830 consistently.
2. RADIO/RTC0/TIMER0 are used directly by the vendor 2.4 GHz code and are SD-owned once the SD is enabled: BLE and the dongle link need a mode switch, never both.
3. Keep restore ready: `pyocd flash -t nrf52840 --base-address 0x0 _backups/2026-10-25-working/full_flash_1MB.bin` (verified to restore a working mouse during this session).

## 9. Artifacts

- `out/s140_730_golden27000.hex` (sha256 011aefbd…), `out/golden_app_27000.bin` (0f583a15…), `out/stub_golden27000.hex` (stub-only test image), `out/s140_nrf52_7.3.0_softdevice.hex` (input copy).
- `work/relocate.py`, `unpack.py`, `equiv.py`, `mkhex.py`, `scan.txt`, debug scripts.
- `HANDOFF_3.md` (running log), this report.
