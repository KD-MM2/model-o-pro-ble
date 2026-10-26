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
| 6 | Plug USB (cable to a PC), move, unplug | `usb: 0 -> 1 -> 0`, cursor follows the right transport |
| 7 | Hold DPI+Back+Forward → dongle mode → same chord back | two `REBOOT`s expected (mode switch) |

## USB/CORE checklist (cable to a PC with Glorious CORE; `watch.py` still running)

Change a DPI stage value, change an LED effect and colour, remap a button, record and run a macro,
change the polling rate, save/switch profiles, then unplug and replug. Expect settings-page hash
changes, no `FAULT`, no unexpected `REBOOT`, and the settings surviving a power cycle.
