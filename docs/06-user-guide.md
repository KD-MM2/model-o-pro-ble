# 06 — Using the mouse

## 1. Transport priority

| Situation | What moves the cursor |
|---|---|
| USB cable plugged in | **USB**, always. The BLE link (if any) stays connected but receives only a neutral (all-released) report at the moment USB takes over. |
| Cable unplugged, BLE mode | **BLE** to the bonded host |
| Dongle mode | The stock 2.4 GHz link (SoftDevice off) |

So "plug into a Linux PC while paired to a Windows PC" moves the Linux cursor, not Windows. This
was an explicit design choice. Unplugging returns to BLE. After a mode switch or reboot the
same rules apply.

## 2. Button chords (hold for 3 seconds)

| Chord (all held together) | Action | Result |
|---|---|---|
| **DPI + Back + Forward** | Toggle **BLE ⇄ 2.4 GHz dongle** mode | Releases buttons on the host, writes the mode record, resets, boots in the other mode |
| **Left + Right + DPI** | **Force re-pair** | 3 purple blinks → the bond is erased and the BLE address changes → reset → boots in pairing mode (2 purple blinks) |

The mode chord works in both modes (so you can always get back); the re-pair chord only acts in BLE mode (it needs the SoftDevice). The hold
time is 98 304 ticks of the 32 768 Hz RTC = exactly 3 s. Releasing early cancels.

The chord masks are plain GPIO bitmasks in RAM (`S.chord_p0/p1`), patchable live over SWD
([08 §6](08-debugging.md#6-live-tuning-hooks)); the defaults are compiled in
`CHORD_P0_DEFAULT`, `CHORD_P1_DEFAULT`, `PAIR_P1_DEFAULT` at the top of `blehid.c`.

## 3. LED feedback

Uses the stock RGB LED PWM; the module temporarily overlays the three duty values at
`0x20003270` and restores them afterwards (300 ms on / 500 ms period, ~75 % duty).

| Pattern | Meaning |
|---|---|
| 2 × **blue** at power-up/reset | BLE mode, bonded to a host |
| 2 × **purple** at power-up/reset | BLE mode, **no bond** (pairing mode: advertising, ready to pair) |
| 2 × **green** at power-up/reset | 2.4 GHz **dongle** mode |
| 1 × **blue** | BLE host connected |
| 3 × **purple**, then reboot | Force re-pair accepted |
| 2 × blue after a long idle | Woke from System OFF (it is a full reboot) |

LED bit mapping in code: bit0 = red, bit1 = green, bit2 = blue (so colour `5` = red+blue =
purple, `4` = blue, `2` = green).

## 4. Pairing

The mouse advertises as **"Model O PRO Wireless"** (HID appearance 0x03C2, Mouse), LE legacy
pairing, **Just Works** bonding. The bond (LTK, peer identity, CCCD state) is stored in flash
page 0xFD000, so it survives power cycles **and normal firmware updates**.

### Windows

1. Settings → Bluetooth & devices → Add device → Bluetooth → pick "Model O PRO Wireless".
2. First time, or after a re-pair: if an old entry exists, **remove the device** first.
   Force re-pair changes the mouse's BLE address, so Windows sees a *new* device; the old entry
   becomes stale — remove it to keep Settings clean.
3. If Windows shows "Connected" but the cursor is dead and `LOG` shows event ids
   `0x10,0x23,0x24,0x14,0x11` repeating, Windows holds a bond with keys the mouse no longer
   has. Remove the device (and its leftover PnP nodes, see [09](09-test-rig.md)) and pair again.

### Linux (BlueZ) — *untested here, standard procedure*

```bash
bluetoothctl
power on; agent on; default-agent; scan on
pair <MAC>; trust <MAC>; connect <MAC>
```

### Force re-pair (new identity)

1. Optional but cleaner: remove the mouse from the host's Bluetooth list.
2. Hold **Left + Right + DPI** for 3 s; see 3 purple blinks, then 2 purple blinks after the reboot.
3. Pair as above. The mouse now has a new random-static address derived from the "pairing
   generation" counter (config word 3), so hosts cannot replay the old key.

## 5. Battery level

The stock battery code (ADC → lookup table → percent, orig 0xE088 → byte `0x20003076`) is reused
as is. BLE exposes it through the standard **Battery Service (0x180F / 0x2A19)**, with notify.

* The value is **noisy for the first seconds after boot**; the module only publishes a value
  that has been stable for 3 s.
* Windows: Settings → Bluetooth & devices shows the percentage; on Linux `upower -d`.
* Scripted read: [09-test-rig](09-test-rig.md) `ble_battery.py`.

## 6. Power behaviour

| Phase | Behaviour | Why |
|---|---|---|
| Boot + 3 s, no USB | 32 MHz crystal (HFXO) released to the SoftDevice | the stock firmware starts it directly before the SoftDevice exists, so the SoftDevice never knew to stop it |
| Advertising | 50 ms interval for 30 s (after boot/disconnect), then 500 ms | quick reconnect, then cheap |
| Connected + moving | 7.5 ms interval, slave latency 0 | low latency (~72 reports/s measured) |
| Connected + 5 s without a report | 15 ms interval, **slave latency 20** | most connection events skipped; first movement returns to fast parameters within about a second |
| 420 s (7 min) idle | stock sleep path → release buttons, disconnect → **System OFF** via the SoftDevice (`sd_power_system_off`) | the stock path wrote POWER directly and faulted → reboot loop |
| Any button press while in System OFF | wake = full reboot (2 blue blinks), reconnect to the bonded host | |
| USB attached | HFXO stays on (USB needs it) | |

The 420 s timeout is the stock firmware's idle sleep counter (`0x20003048`, +1/s, threshold u16
at `0x200038CB`); Glorious CORE's sleep setting changes it.

**Not measured:** no current meter was used. The savings are inferred from register state
(HFXO about 0 % on in idle versus 100 % before; radio events per second). Remaining always-on
draw is the stock 1 kHz TIMER1 tick and the LED PWM; see
[11 — ideas](11-history-and-next.md#ideas-not-done).

## 7. Settings, DPI, remaps, macros

All of the vendor's behaviour is unchanged: DPI stages, lift-off, polling-rate profile, button
remap and macros live in the stock firmware and its vendor settings pages (0x8B000/0x8C000).
Glorious CORE configures them over **USB** (HID vendor interface, 258A:2015) as before. Our
module only moves the finished HID report to BLE. Clicking DPI used to reboot the mouse (the
stock settings write used direct NVMC while the SoftDevice was on); this is fixed by routing
the vendor's flash erase/write through the SoftDevice flash API.

## 8. What the HID reports look like

7-byte input report, Report ID 1:

| Byte | Content |
|---|---|
| 0 | buttons 1–8 (L, R, M, Back, Forward, + 3 more) |
| 1–2 | X, int16 relative |
| 3–4 | Y, int16 relative |
| 5 | wheel, int8 |
| 6 | horizontal pan (AC Pan 0x0238), int8 |

This is the Model O3 layout (8 buttons). The stock builder's buffer is ordered
`[0] buttons [1] wheel [2:3] X [4:5] Y [6] pan`; `blehid_tx_stock` reorders it to the BLE layout
above.
