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

## 2. Button chords

| Chord (all held together) | Action | Result |
|---|---|---|
| **DPI + Back + Forward** | Toggle **BLE ⇄ 2.4 GHz dongle** mode | Releases buttons on the host, writes the mode record, resets, boots in the other mode |
| **Left + Right + DPI**, hold **10 s** | **Wipe all hosts** (factory reset of the pairings) | 3 purple blinks → every stored host is erased and the BLE address generation changes → reset → boots in pairing mode (2 purple blinks) |
| **DPI + Left**, hold **3 s** | **Add a host** (open the pairing window) | 2 purple blinks, then one purple blink every 2 s for 120 s while the mouse is open for pairing; stored hosts are kept |
| **DPI + Forward** / **DPI + Back**, hold **1 s** | **Next / previous host** | blue blinks = host number (1–4); the link moves to that host 1.5 s after the last press |

The mode chord (3 s, 98 304 RTC ticks) works in both modes (so you can always get back); the host chords only act in BLE mode (they need the
SoftDevice). Releasing early cancels. The wipe chord is deliberately long (10 s): it used to be 3 s and fired by accident while trying to
add a host. While a chord is held the buttons still reach the current host (a Left click, a Forward click, a DPI step).

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
| 3 × **purple**, then reboot | Wipe-all accepted |
| *k* × **blue** after DPI + Forward/Back | host *k* selected (it connects within about 1–2 s) |
| purple blink every 2 s | pairing window open (120 s) |
| 2 × blue after a long idle | Woke from System OFF (it is a full reboot) |

LED bit mapping in code: bit0 = red, bit1 = green, bit2 = blue (so colour `5` = red+blue =
purple, `4` = blue, `2` = green).

## 4. Pairing

The mouse advertises as **"Model O PRO Wireless"** (HID appearance 0x03C2, Mouse), LE legacy
pairing, **Just Works** bonding. Up to **4 hosts** are stored (LTK, peer identity, CCCD state each) in flash
page 0xFD000, so they survive power cycles **and normal firmware updates**.

### Several hosts (PC, phone, …)

* **First host:** a mouse with no stored host advertises and accepts pairing by itself (2 purple blinks at boot). Pair it as below.
* **More hosts:** hold **DPI + Left** for 3 s, then add the mouse on the new host within 120 s. The mouse drops the current host and
  advertises from a fresh address while the window is open, so none of the stored hosts can grab the connection. A host that is already
  stored gets its own slot back (same identity), otherwise the next free slot is used; with all 4 slots full the **oldest** host is replaced.
  Pairing is refused outside the window.
* **Switching:** **DPI + Forward** goes to the next stored host, **DPI + Back** to the previous one, wrapping around, only among the stored
  hosts (1→2→3→4→1…, with two hosts 1→2→1). Press repeatedly to step further; the link moves 1.5 s after the last press. The selection is
  remembered across power cycles.
* **How it works:** every stored host has its **own advertising address**; only the selected host's address is on air, so only that host can
  connect. Consequences: a scanner that is not a stored host sees extra "Model O PRO Wireless" entries (one per slot and per pairing window,
  harmless); a host reconnects after a switch within about 1–2 s on Windows and Android in our tests, but the time is the host's own
  reconnect scan and can be longer.

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

### Wipe all hosts (new identity)

1. Optional but cleaner: remove the mouse from every host's Bluetooth list.
2. Hold **Left + Right + DPI** for **10 s**; see 3 purple blinks, then 2 purple blinks after the reboot.
3. Pair as above. The mouse now has new random-static addresses derived from the "pairing
   generation" counter (config word 3), so hosts cannot replay the old keys.

## 5. Battery level

The stock battery code (ADC → lookup table → percent, orig 0xE088 → byte `0x20003076`) is reused
as is. BLE exposes it through the standard **Battery Service (0x180F / 0x2A19)**, with notify.

* **Startup transient:** the stock code resets its percentage to 100 on every boot and every charger-state change (USB plug/unplug), then
  slews it down to the measured level within ~25 s. BLE publishes a new level only after the stock value has been **stable for 30 s**, and the
  last published level is **kept in RAM across soft resets** (watchdog, mode switch, reflash), so a reset does not re-announce 100.
  A cold start (battery just inserted, or wake from System OFF with RAM lost) shows the stock value until the first stable one, so hosts can
  see 100 for up to about a minute.
* **Accuracy:** it is the stock ADC measurement. It settled at 36 % on one boot and 43 % on the next with the same battery (charger/load
  conditions differ), so treat it as ±~7 points.
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
