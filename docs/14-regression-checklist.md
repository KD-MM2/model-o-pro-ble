# 14 — Regression checklist for rarely used stock paths (open issue 8)

Purpose: the relocation left ~380 words unpatched on purpose. A missed pointer only shows up when
that code path runs, so run each feature once after any change to `relocate.py`/`mk_ble.py`, and
watch the chip while you do it:

```bash
python tools/watch.py 240          # non-halting; prints REBOOT / FAULT / state changes; exit 1 on reboot or fault
```

## Static audit (reproducible, done 2026-10-26)

| Check | Result |
|---|---|
| Remaining words that still look like old-range pointers | 383 |
| …of which loaded by a PC-relative load | 20, all false positives (strings `"%s"`/`"%c"`, CRC poly 0x11021, mis-decoded data words) |
| …that look like Thumb function pointers (odd, target = `push` prologue) | 1 (`0x11ee8`), a `b.w` tail + padding, not a pointer |
| …forming runs ≥ 2 | 7, all instruction halfwords / string tails |
| `movw`/`movt` pairs building old-range addresses | 0 |
| …remaining with value < 0x10000 and plausible data target | 209, dominated by `0xBD10`/`0xBD70`/`0xBD38` (`pop {…,pc}` + padding), `0x632E` (`".c"`), T32 instruction halves |
| Patched words (585): odd values whose target decodes as an instruction | 191 / 191 |
| Patched even values: aligned data/table targets | 374 aligned, 12 zero, 5 unaligned (string pointers), 3 table bounds |

Conclusion: no evidence of a missed or false pointer. Static analysis cannot prove it, hence the
dynamic checklist below.

## Dynamic checklist (BLE mode, cable unplugged, `watch.py` running)

| # | Action | Expect |
|---|---|---|
| 1 | Click DPI through every stage and back (≥ 8 clicks) | LED indication, no `REBOOT`, settings page 0x8B000/0x8C000 hash changes |
| 2 | Left/right/middle/back/forward, hold each 2 s | `report buffer` bit changes, host sees the button |
| 3 | Fast wheel scroll both ways, tilt/pan if present | wheel byte changes, no fault |
| 4 | Lift the mouse and put it down, fast flicks | cursor follows, no fault |
| 5 | Leave idle 90 s, then move | idle link params, then fast again |
| 6 | Plug USB (cable to a PC), move, unplug | `usb: 0 -> 1 -> 0`, cursor follows the right transport; run `faultcatch.py` for this one |
| 7 | Hold DPI+Back+Forward → dongle mode → same chord back | two `REBOOT`s expected (mode switch) |

## USB/CORE checklist (cable to a PC with Glorious CORE; `watch.py` still running)

Change a DPI stage value, change an LED effect and colour, remap a button, record and run a macro,
change the polling rate, save/switch profiles, then unplug and replug. Expect settings-page hash
changes, no `FAULT`, no unexpected `REBOOT`, and the settings surviving a power cycle.

## Results

### Run 1 — 2026-10-26, BLE mode, 240 s, cable unplugged (`watch.py`)

* **0 fault events** (CFSR/HFSR stayed 0). No unexpected reboot.
* **DPI clicks:** the settings page 0x8B000 hash walked through the same 4-state cycle twice
  (`133464411 → 3857245105 → 308236757 → 2351231033 → 133464411`), i.e. four DPI stages, each click
  writing the vendor settings page through the SoftDevice flash path, with **no reboot** (the original
  DPI-click reboot bug stays fixed).
* **Buttons / wheel / motion:** report buffer showed button bits (left, 0x10, 0x18 = back+forward held),
  wheel and X/Y deltas as expected.
* **Mode chord round trip:** BLE → DONGLE at ≈127 s (`sd: 1 → 0`, mode record 1 → 2, RTC reset), DONGLE →
  BLE at ≈137 s (`sd: 0 → 1`, mode record back to 1, `conn` re-established). The dongle-mode boot path
  (init_nosd, SoftDevice off) therefore runs and the chord works in both directions.
* `probe error: STLink error (16): AP wait` lines appear while the stock firmware erases/writes flash:
  the NVMC stalls the bus, so the probe times out for a moment. Benign.

Not covered by run 1: USB plug/unplug (verified earlier in the session: `258a:2015` enumerates, direct-USB
flag set), a full 90 s idle, and the Glorious CORE checklist (macros, remaps, polling rate, LED effects).

### Run 2 — 2026-10-27, USB attached to a Windows PC with Glorious CORE (`watch.py`, 420 s)

* USB stayed attached for the whole run (`usb=1`, vendor mode var 0); the BLE link stayed up in the background.
* Two device writes from CORE were visible: both vendor settings pages (0x8B000, 0x8C000) rewritten at ≈134 s,
  the first page again at ≈197 s. **No fault, no reboot** in the log.
* The owner ran the CORE list (DPI stage, LED effect/colour, button remap, macro record + run, polling rate,
  profile save/switch, replug, close/reopen CORE): **no errors, all settings persisted, and the modified
  settings and features worked.** (The unplug/replug itself was not visible in the monitor log.)

Verdict for open issue 8: the vendor USB configuration channel, settings flash writes, DPI, LED, remap,
macro and polling-rate paths work after the relocation; the static audit found no missed pointers. Remaining
unexercised: the stock CLI and the 2.4 GHz link itself (dongle).

### Run 3 — 2026-10-27: unplug after CORE faulted; root-caused and fixed

* `watch.py` showed `usb: 1 → 0`, `mode: 0 → 1` and `HFSR=0x40000000` at the unplug, then repeated settings-page rewrites, and the mouse stopped
  working (the watchdog reset it later). **This was a real bug in a rare path, found only because of this checklist.**
* `faultcatch.py` (new) located it: `app_error_fault_handler(id=0x1001 APP_MEMACC)` at orig `0x15A34`, then (after the first gate) at `0x18ADE`.
  Cause: the stock 2.4G link state machine handles "USB removed" by setting the mode var to 1 and powering the radio/TIMER0 up; the SoftDevice owns both.
  The boot path and the sleep path were already gated; this one was not (and it only ran when the radio-init flag `[0x2000361D]` was 0).
* Fix (`mk_ble.py`): gate `bl 0x15A1C` (0x19B84), `b.w 0x18AD0` (0x19B8C), `b.w 0x15B70` (0x19B0E) and, for the CORE wireless-parameter
  command, `bl 0x16740` (0x14880) so they run only with the SD off. The mode-var write is kept (BLE transport depends on it).
* Result: owner repeated the CORE → unplug → replug cycle several times (including a quick one and a CORE close/reopen) with the trap armed for 420 s:
  **no fault**, mouse kept working over BLE after every unplug and over USB after every replug. `watch.py` afterwards: 0 faults, 0 reboots.
* New image sha256 `d52120ccf9a3a79715ffbc104d89daad8246ebeae59626a8605c12837d812175`; backup `_backups/2026-10-27-ble-stable-v5-radio-gates`.

Lesson: the static audit and a clean CORE session were not enough; the unplug *after* CORE use is a different path. Add "unplug/replug after every
CORE feature" to the checklist, and keep `faultcatch.py` armed during any new feature test.

### Run 4 — 2026-10-29, multi-host (item 7), two real hosts (Windows PC + phone)

What was exercised on hardware: pairing the first host, adding a second through DPI + Left, switching with DPI + Forward/Back, re-pairing
an already stored host, mixed with the user pressing the chords by hand.

* **Fault trap:** `faultcatch.py` armed for 10 min during switching: no fault. `CFSR/HFSR` stayed 0 in every status read.
* **Cycle order** (SWD hook with fabricated bonds, 4/3/2/1 configured hosts): Forward 1→2→3→4→1…, Back 4→3→2→1→4…, with two hosts 1→2→1→2, with one host no change.
* **Two real hosts:** every switch ended connected to the right host (`SEC_INFO_REQUEST` matched the expected slot) **1.6–2.8 s after the press**
  (1.5 s of that is the debounce). Passive trace of the user's own switching: 11 target changes, every one caused by a physical DPI + Forward.
* **Re-adding an already stored host** kept the slot count at 2 (same-identity replacement).
* **Real bugs found and fixed on the way** (each only visible in a test with real hosts):
  1. *Wipe chord fired by accident* (3 s Left + Right + DPI while trying DPI + Left): generation 4 → 13 in one session, all hosts erased each time. Now 10 s.
  2. *Open pairing window let the old host take the connection back within 0.3 s* (all hosts shared one address). Now one address per host.
  3. *Nonce read from the flash page while it was being rewritten* → wrong advertising address for 60 s after a switch (reconnect after 63–66 s,
     once "never"). Now everything reads a RAM mirror; verified with `sd_ble_gap_adv_addr_get` = expected address on every switch.
  4. *New slot loaded while the old host was still connected* (a late CCCD write could have been saved into the wrong slot). Now loaded after the disconnect.
* **Not verified:** pairing refusal outside the window, a third/fourth real host, Linux/macOS hosts, power draw while advertising 30 ms for 60 s after a switch.
* New image sha256 `5f594448c9de6e2fe5e10351e0c66f6bfd4ec1c447cc7bd35ff3e89b5053ed64` (blob 8256 B).

### Run 5 — 2026-10-29, LED regression found by the owner

After item 5 ("stop PWM0 while the status LED is dark") the owner reported that the **DPI LED no longer lit when the mouse was lifted**. I had verified the
status LED only (PWM0 enabled during the boot blink, disabled afterwards, blink seen) and not the other LED.

* Cause: the stock LED engine is clocked by PWM0's loops-done interrupt for both LEDs ([07 §13](07-internals.md#13-the-stock-led-engine)); with PWM0 stopped the DPI LED state froze.
* The gate was removed (build `blehid.c` without `led_pwm_gate`); PWM0 and PWM1 are both enabled while awake, the DPI LED shows its colour after boot.
* Awaiting the owner's lift/place check on the fixed image. Lesson: an optimisation that touches a stock peripheral needs a check of **everything** that peripheral serves, and the owner
  noticing a behaviour change is a regression signal; add "lift the mouse, click DPI, watch both LEDs" to the checklist.
