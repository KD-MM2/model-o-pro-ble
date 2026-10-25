> **Raw worklog** kept for provenance. It was written incrementally while the project was being figured out, so early sections contain beliefs that later sections correct. Treat the numbered guides in `docs/` as authoritative.

# HANDOFF 3 — relocated golden app built + host-verified (2026-10-25, all work under work/)

Nothing was flashed. Probe was only read: UICR APPROTECT=0xFFFFFFFF, SWD connects fine (on this silicon 0xFF = open; the "0x5A" in HANDOFF.md is not what the chip holds).
Another agent owns the canary hex test (_re_work/canary, output/FLASH-CANARY.md) — do not run two flashes on the probe at once.

## Deliverables (work/out/)
- golden_app_27000.bin   sha256 5688550f…  (golden_app.bin rebased 0x6000→0x27000, 94727 B, ends 0x3e207)
- s140_730_golden27000.hex  sha256 9a64d8d4…  = Nordic MBR+S140 7.3.0 (0x0–0x26497) + relocated app @0x27000. NO UICR records. Does not touch 0x8B000/0x8C000.
- Flash (when user says GO; destroys current 0x0–0x3E206 incl. stubs; restore = _backups/2026-10-25-working/full_flash_1MB.bin):
  `pyocd flash -t nrf52840 -f 200k out/s140_730_golden27000.hex && pyocd reset ...`
  Expected: SD never enabled by the app (flag 0x20003830==0), so it behaves like the working bench build (wired mouse + USB); proves MBR/SD/0x27000 layout. BLE still needs the enable patch (not done).

## Tools (work/work/)
- relocate.py [base] [out]  patcher; unpack.py (IAR packbits decoder for RAM-init blob); equiv.py (Unicorn: run orig@0x6000 vs reloc@0x27000, compare PC traces + RAM); rebase_scan.py/scan.txt (copy of other agent's scanner); mkhex.py.
- venv: reused ../_re_work/.venv-probe (has pyocd, intelhex); system python3 has capstone/unicorn.

## Findings that correct earlier notes
1. The other agent's scanner (124 must-change + 696 "ambiguous") is INCOMPLETE: it mis-decodes literal pools as code (e.g. pool @0x64CC/0x64D0 = INIT table bounds) and misses them. ~20 extra pointers found; ~170 "ambiguous" words are false positives (string tails like "%s\0\0", `pop{..,pc}`+pad halfwords, constants 0x11021 CRC poly, 0x8200/0x8402 key tables, 0x76A8 bss length). relocate.py documents each filter. Final patch set = 615 words.
2. INIT table @0x1C710: entry0 = IAR packbits blob @0x1C944 (844 B → 0x8A8 B to RAM 0x20003000) with FLASH POINTERS inside (HID report-desc table, strings, device name, observer tables, 0x8361/0x13d5b fn ptrs). A flash-only rebase misses these. relocate.py decodes, patches 24 words, and re-packs (literal-only tokens, 2.2 KB; table src unchanged address). Entry1 (0x1CC90, len 0x76A8, fn 0x7210) is the .bss clear — NOT 30 KB of code; its src is unused. Handoff 1 "missing blob" worry is moot.
3. Packbits: token t: lit=(t&7) (0→next byte), z=(t>>4) (0→next byte); copies lit-1 literal bytes; if t&8 then copy z+2 bytes from dst-offset(next byte) else z zero bytes.
4. App never writes VTOR, never touches UICR → compatible with SD owning VTOR; SD forwards to app vector table at 0x27000 by default (svc 0x13 optional).
5. Host verification: equiv.py, 8M instructions, 2222 unique PCs: PC traces identical (decompress routine excluded) and every RAM diff is exactly +0x21000 on a pointer; no other diffs. Only executed paths are proven — hardware bench is the real test. Emulator hacks: HFCLK/LFCLK events set on task write; peripheral read-poll loops released after 16 reads.
6. Unicorn found the 0x1b010 word 0x7d65 (fn ptr hidden in a string-looking region) — shows blind filters can miss pointers in cold paths; if the bench asserts/hardfaults, suspect unpatched pointer first (run equiv.py deeper, add coverage).

## Next
1. User GO → flash out/s140_730_golden27000.hex, check wired mouse (+ read 0x20003830 stays 0, no fault: CFSR 0xE000ED28 clear first).
2. Then BLE enable patch: at boot call nrf_sdh_enable_request (reloc 0x32C18 = 0x11C18+D... verify), sd_ble_cfg_set/sd_ble_enable (svc 0x69/0x60), gate vendor 2.4G radio (RADIO/RTC0/TIMER0 owners) — study in output/S140-STUDY.md §e.4.


## UPDATE — flashed on hardware (user GO) — WORKS
Final image: out/s140_730_golden27000.hex = MBR+S140 7.3.0 + relocated app @0x27000. Flashed with pyocd; mouse enumerates 258a:2015 (kbd+mouse hidraw), CFSR=0, thread mode, flag 0x20003830=0, re-enumerates after SWD reset. (Another agent's canary had briefly overwritten 0x27000 — user then paused them.)
Iterations (bugs the host-side Unicorn test could NOT see because it never ran IRQ/USB paths):
 1. scanner "pool" words that were really `pop {..,pc}`+pad halfwords got +D -> corrupt instruction (0x124F0, ISR stack imbalance). Fix: words <0x10000 in code need an LDR-literal loader.
 2. 0x1afd0 = 0x8725 (USB-power event handler ptr, inside a config struct) was excluded as "constant"; unrelocated pointer landed in S140 code -> HardFault. Also 0x8201/0x8401/0x8403 (key constants) were wrongly patched.
 3. 0xe19c=0xe1bd (app_timer callback, loader not detectable) and CLI table entries 0x1ac28/38/d0/e0 (0xf3a9.. fn ptrs) had been dropped by instr/loader filters.
Lesson: a stub-only build (no SD, old 0x6000 area still holding S140 bytes) HIDES stale old-address pointers — to test pointer completeness, erase 0x6000–0x26FFF... or better, check the relocated app on SD build. Remaining unpatched in-old-range words in image: ~380 (instruction halfword pairs, string tails, constants) — unverified for rarely used paths (BLE, CLI, dongle link); suspect an unrelocated pointer first if a fault appears there. Debug tooling in work/: trace3*.py (IRQ trace via breakpoint+step), st.py/fr.py (fault state/frame), wp.py (DWT watch), ev.py.
Tip: crash frame at HardFault `b .` (0x273e6): MSP points at stacked frame [r0-r3,r12,lr,pc,xpsr].
Next: BLE enable patch (nrf_sdh_enable_request @0x32C18, svc 0x60/0x69), radio-mode switch vs vendor 2.4G.

## UPDATE 2 — BLE enable patch (stage 1: SD enabled + advertising), flashed 2026-10-25
Image: out/s140_730_golden27000_ble.hex (built by work/mk_ble.py from golden_app_27000.bin; flash with ./flash_test.sh out/...hex). Mouse still enumerates over USB (258A:2015, kbd+mouse) with the SoftDevice ENABLED; every SD call in the stub returned 0 (log @0x2003F000: [4]=power_init 0, [8]=sd_enable 0, [0xc],[0x10] cfg_set 0, [0x14] ble_enable 0, [0x18]=0x20002E00 SD RAM end (< app RAM 0x20003000), [0x1c] adv_set_configure 0, [0x20] adv_start 0, [0x24]=B1E0FFFF done).
What the patch does (all in a 344 B stub @0x3F000, hooked at the `bl 0x6F68` (app_usbd_init wrapper) in main, orig 0xE878 / reloc 0x2F878):
 1. init the SDK app_scheduler struct @0x20003704 (never initialised in this build; SD events are dispatched via app_sched -> SWI2 ISR asserted NO_MEM without it); queue in 0x2000B000..
 2. nrf_drv_power_init(NULL) BEFORE the SD is enabled (app_usbd_init calls it again and only tolerates 0x85 already-initialised; with SD on it returns 8 -> assert)
 3. nrf_sdh_enable_request (app's own SDK routine, 0x32C18)
 4. sd_ble_cfg_set: attr table 248 B (min) and vs_uuid_count 0 -> SD RAM fits below 0x20003000 (default config needs 0x20003328 -> would overlap app .data)
 5. sd_ble_enable, then pump flag 0x20003833=1 (nrf_sdh_ble evt poller gate)
 6. adv_set_configure/adv_start: connectable scannable undirected, 100 ms, adv data = flags + complete name "Model O PRO Wireless".
Binary patches in the app (mk_ble.py PATCHES): 0x6F94 `ldr r1,=POWER->DCDCEN; str r0,[r1]` -> `svc #0x3f` (sd_power_dcdc_mode_set(1); SD forbids the direct write); 0xE88A `bne`->`b` to skip the vendor 2.4G radio init (0x15A1C/0x18AD0 write RADIO regs which S140 owns).
How the faults were diagnosed: SD calls app_error_fault_handler(id=0x1001=NRF_FAULT_ID_APP_MEMACC, pc, info=subregion) when the app writes an SD-protected peripheral register; id 0x4001 = SDK assert with (line,file) on the stack. Breakpoint at the handler (reloc 0x28474) from reset: work/bp.py.
KNOWN LIMITS / RISKS: (a) vendor 2.4G dongle link is DISABLED in this build (radio init skipped) — BLE and 2.4G are mutually exclusive on RADIO; (b) a central CONNECTING is untested: the app's BLE observers (adv/pm/gatt) never ran before and the GATT/HID services are not registered -> possible assert/reset on connect; stage 2 = run the app's own BLE init (gap/gatt/pm/hids/conn params); (c) no BT adapter on this host: advertising confirmed only by SD return codes + phone scan.

## UPDATE 3 — Stage 2: pairing + HID mouse over BLE WORKS (tested with g15 Windows), 2026-10-25
Image: out/s140_730_golden27000_ble.hex = `cd work/blehid && ./build.sh && cd .. && python3 mk_ble.py 720` (C toolchain: work/.venv-tc = pip ziglang 0.13 → `zig cc` + lld; llvm-objcopy-21 from system).
Layout: stub (asm SD bring-up) @0x3F000, thunk @0x3F800, blob (blehid.c, 2 KB) @0x40000 with entry table {init, tick, send, &state}; blob RAM (state) @0x2000B400 (NOT 0x2000C000-unverified), sched queue 0x2000B000, log 0x2003F000 (stub) / 0x2003F100 (blehid: [1]=init stage/err 0x1000=ok, [2]=event count, [3..18]=event ids ring, [0x20]=last notify err (0xFFFF=not ready), [0x21]=sent count (uninitialised base!)).
blehid.c: GAP name/appearance(0x03C2)/PPCP; services DIS(PnP 258A:2015), BAS(100%), HID(Info, Report Map, Control Point, Protocol Mode, Report in+ref); adv = flags+appearance+HID UUID, name in scan response; SMP legacy Just Works bonding (own enc key + peer enc/id kept in RAM — LOST ON RESET); handles SEC_PARAMS/SEC_INFO/PHY/DLE/MTU/SYS_ATTR; per-main-loop poll (sd_ble_evt_get) via thunk at main-loop tail (orig 0xE92C `bl 0x14AE4`); blehid_tick runs the app's report builder 0x14AE4, then if flag byte 0x200032DE bit3 was set forwards the app's fresh 8-byte report @0x200032E8 ([0]btn [1]wheel [2:3]X [4:5]Y [6]pan) as my 7-byte report (btn,X16,Y16,wheel,pan) via sd_ble_gatts_hvx.
Bugs hit: .bss is NOT zeroed (RAM uninitialised) → memset(&S) in init; SD keeps pointers to adv buffers → static RAM not stack; app_sched never initialised (SDH dispatch via app_sched) → stub inits it; DCDCEN direct write and vendor 2.4G radio init forbidden/skipped.
Test rig (g15, Windows, ssh): python venv C:\Users\KaoTD\blevenv with bleak; scripts in work/g15: ble_scan.py, ble_pair.py, ble_unpair.py, cursor.py, run_task.cmd. PAIRING MUST RUN IN THE INTERACTIVE SESSION (ssh session gets ACCESS_DENIED): `schtasks /Create /TN blerun /TR "C:\Users\KaoTD\run_task.cmd ble_pair.py" /SC ONCE /ST 23:59 /RU kaotd /IT /F` then `/Run /TN blerun`; output in C:\Users\KaoTD\out_ble_pair.py.txt. After re-flashing the mouse (new keys) you MUST remove Windows' bond first: ble_unpair.py + `pnputil /remove-device` on Get-PnpDevice nodes matching D6BFB2D943F2 (mouse addr D6:BF:B2:D9:43:F2), else Windows retries encryption forever (symptom: event loop 0x10,0x23,0x24,0x14,0x11).
Verification done: pair OK (events 0x13, reply ok, 0x19 auth status 0), notify enabled, injected motion via SWD writes to 0x200032E2/E4 + flag |= 8 (work/inject.py) moved the Windows cursor accordingly (cursor.py).
NOT verified: real sensor motion/buttons (needs the user to move/click and a check of LOG[0x21]/cursor), USB wired (VBUS was absent; replug), bond persistence across mouse reset, reconnect after Windows sleep, battery %, DPI/profile features, 2.4G dongle mode (disabled), multi-host.

## UPDATE 4 — bond persistence + boot-time mode switch (BLE <-> DONGLE), 2026-10-25
Flash pages (outside app/SD): 0xFD000 = bond record (128 B: magic B0DD0001, checksum, own LTK/master id, GATT system attributes=CCCD state; written via sd_flash_* state machine with BUSY retry + verify; loaded in blehid_init), 0xFE000 = mode record {C0DE0001, mode, ~mode} (1 = BLE default, 2 = DONGLE).
Verified: pair once, reset mouse (pyocd reset / reflash) -> Windows reconnects by itself, link re-encrypted with stored LTK (SEC_INFO_REQUEST), CCCD restored via sys_attr_set at CONN_SEC_UPDATE (reconnect flag) -> reports flow (cursor test). No re-pair needed. (hvx before sys attrs are set returns 0x3401 SYS_ATTR_MISSING; the SD only raises the event on a peer ATT request.)
Mode switch: stub reads 0xFE000 at boot. DONGLE = SD never enabled, original vendor path (radio init, USB/2.4G); BLE = SD + blehid. Conditional app patches: 0x6F94 DCDCEN write -> thunk @0x3F840 (svc 0x3f if SD on, direct write otherwise); 0xE888 `cmp r0,#1; bne` -> gate @0x3F880 (skip vendor radio init when SD on). Toggle = button chord held ~3 s (RTC1 counter) -> writes the other mode (BLE: sd_flash then reset; DONGLE: direct NVMC then reset). Chord pin masks live at runtime in S.chord_p0/p1 (address = ENTRY[5] = 0x2000B680/84; default 0 = disabled; active-low GPIO IN masks of P0 (0x50000510) / P1 (0x50000810)). Round trip tested by poking the mask to a low pin via SWD (pyocd write32 0x2000b680 1).
vendor mode var @0x20003003: 1 = USB, 2 = 2.4G radio (report builder 0x14AE4 dispatches on it); radio init runs at boot when it is 1.
TODO: calibrate button pins (work/gpio_watch.py while the user presses buttons), bake defaults into CHORD_P0/P1_DEFAULT, real-sensor motion test over BLE, USB + BLE together (needs VBUS), real dongle test (no dongle available on g15/this host), reset reasons/LED feedback on mode change, multiple bonds.

## UPDATE 5 — O3 Wireless firmware triage (o3/)
Source: firmwares/Model_O3_Wireless_Black-1.3.3_*.zip -> mouse/mouse_dfu_package.zip -> mouse_black.bin (164840 B, plaintext Thumb, entropy 6.8; .dat is only the signed DFU init packet, irrelevant for SWD flashing).
- nRF52840 (SP 0x2003ff90), app linked at 0x27000 (same slot as our relocated app), uses SD SVCs incl. 0x60 ble_enable, 0x69 cfg_set, 0x72-0x74 adv, 0xa8.. gatts => S140 7.x BLE app, no relocation needed.
- Modular SDK-style fw: mode_selector, bt_mgr, bt_hid, radio_comm (dongle_comm), power_manager, battery_manager, dpi_manager, led_manager, motion_manager, polling_manager, nrf5x_fds_storage.
- O3-specific HW it expects: bq21040 charger x2, bq27220 fuel gauge (I2C), nrf5x_i2c_1, nrf5x_qdec (wheel), sensor_0 (type unknown), dock. Dongle is nRF-based (own protocol), not compatible with the Pro dongle.
- Pro (stock) uses battery.c (ADC-style) and a different radio protocol.
Verdict pending: sensor identity + pin maps (dump Pro PIN_CNF/PSEL over SWD vs O3 init code).

## UPDATE 6 — O3 as behaviour reference (tool: work/o3dis.py; image base 0x27000)
- Module table at 0x4dd20.. (32 B entries {init_fn, name, ?, ops, ram, 0,0,0}): mode_selector init 0x41a58, bt_hid 0x44af4, bt_mgr 0x45078, battery_manager 0x3e5f4, button_manager 0x45338, usb 0x42e24, radio_comm 0x47a28, motion_manager 0x4237c, sensor_0 0x3c93c, power_manager 0x42b60. Event-bus architecture (subscribe at 0x43970/0x43974, post at 0x437e4/0x438d0).
- O3 BLE HID descriptor @0x4d318 (BLE: keyboard no-ID boot kbd + vendor feature id3 63B + mouse id1): mouse = **8 buttons**, X/Y int16, wheel int8, AC Pan (0x0238) int8 => same layout as ours except 8 buttons (ours 5). USB descriptor @0x4ef54 has ids 1 mouse,2 kbd,3 vendor feature,4 consumer.
- GAP: name "Model O3 Wireless", appearance 0x03C2 (same appearance we use). Standard Nordic SDK pieces (ble_advertising / peer manager / gatt queue), no unusual BLE tricks.
- mode_selector state @0x20003488: [0]=mode (1/2/3), [1]=previous wireless mode, [8]=lock flag; reacts to 2 event sources (descr 0x4e210 type 0xb, 0x4e240 types 0/2); changes persist via 0x42db8 (store key 0xd). Exact semantic of 1/2/3 NOT yet confirmed (likely 1=USB,2/3=BLE/2.4G).
- Takeaways for our firmware: raise buttons to 8 in our HID map; keep mode in flash (done); remember previous wireless mode; USB-plugged => wired mode.

## UPDATE 7 — real sensor motion over BLE works; HID map now 8 buttons
- HID report map: 8 buttons (O3 layout), report still 7 bytes. Windows re-paired (unpair + pnputil clean + pair).
- Root cause of "no movement": stock motion task (orig 0x1319C, runs in main loop) reads the PixArt sensor (SPI2 legacy SPI, sck P0.12 mosi P0.8 miso P0.11, motion irq P0.6 low, burst reg 0x16) and accumulates dx/dy in 0x20003016/0x20003018 (int16), but its consumer is the USB/radio report path which needs a host -> never drained. Also the motion task skipped the burst read when P0.6 was high at poll time: patched `bne` @0x131D2 -> nop (mk_ble.py PATCHES).
- blehid_tick now drains ACC_DX/ACC_DY (zeroed at init) into the 7-byte report, subtracting only what hvx accepted. Verified: LOG[0x21] sent=2243, send result 0, g15 cursor moved with real mouse motion.
- O3 comparison: O3 sensor_0 also PixArt (reads reg 0x00 id / 0x5F inverse id, motion reg 0x02), same family as Pro init table at orig 0x17960.
- Not yet verified: motion direction/speed (units), buttons, wheel over BLE (stock message path 0xE348 loop produces buttons/wheel into 0x200032DE/E8 - untested), USB.
- Debug note: a bkpt @0x284d4 (app error handler, orig 0x74d4) halts the target whenever DWT/FPB debug setup leaves stale state; clear DWT comparators (0xE0001028+16*i) after watch scripts.

## UPDATE 8 — donor survey + button pin map
- Pin map (active low, calibrated by hold-combination captures): LEFT P1.15, RIGHT P1.13, MIDDLE P1.10, BACK P0.9, FORWARD P0.10, DPI P1.0, wheel quadrature A=P0.2 B=P0.29 (direction unverified). Other pulled-up inputs P1.4, P1.6 unidentified. Sensor: SPI2 sck P0.12 mosi P0.8 miso P0.11, motion irq P0.6.
- blehid_tick now samples buttons/wheel from GPIO and sends them with the drained sensor deltas (flashed; real-hand test of buttons/wheel NOT yet reported).
- Donor survey over firmwares/_x: only Model O3 Wireless / D3 Wireless (mouse_black.bin 164840 B, identical size) is nRF52840 + S140 BLE (svc ble_enable/cfg_set/adv) + nRF dongle + USB. V2 wireless mice (MOW/MOMW/MDW/MIW) are a different MCU (reset vector 0x1000xxxx, 'PixArt BLE Keyboard'); Model O/D/I V2 are STM-class (RV 0x080071b5); O2 Pro / Model O Pro stock are 2.4G-only. There is no Model O Pro image with BLE.
- O3 modules are event-bus based (framework primitives ~0x43970/74 subscribe, 0x437e4/0x438d0 alloc+post, 0x42d50/0x42db8 settings get/set, 0x43d20/0x43d44 timers?) - literal transplant needs those shims. work/o3graph.py crude reachability is unreliable (function-end heuristic), do not quote its byte totals.

## UPDATE 9 — reuse the stock pipeline, BLE only as a transport (built, NOT yet flashed)
Rule from the user: DO NOT REINVENT. My earlier GPIO/accumulator/wheel code in blehid_tick was removed.
Findings (USB works fully with SD enabled: cursor, buttons, wheel):
- Real mouse USB endpoint buffer: EPIN1 PTR = 0x200035E5, 8 bytes [0]=buttons [1]=wheel [2:3]=X [4:5]=Y [6]=pan.
- Stock mouse report builder = orig 0x14CEC (runs right after the 0x14AE4 hook at main-loop end, orig 0xE930). If byte 0x2000300C bit2 ("mouse report due", set by the polling timer) it builds the buffer: buttons = [0x200032E8]|[0x20003052]; wheel = [0x200032E9]+[0x20003055]; dx = u16 [0x20003016]; dy = u16 [0x20003018]; pan = [0x20003056]. Then transport: if [0x200035DE]==1 -> direct USB IN 0x84BA; else by vendor mode var [0x20003003]: 1 -> 0x15E5C(buf,1,8,0) returns 1 on success; 2 -> radio 0x9084(0,buf,8) returns 0 on success. On success it clears the accumulators and bit2.
- Button scan = orig 0x16B0C (pins confirmed: 0x2F=P1.15 L, 0x2D=P1.13 R, 0x2A=P1.10 M ...), run once per 1 ms tick (byte 0x2000306C incremented by the TIMER1 tick handler 0x18BA4) together with the macro/remap engine 0xE32C.
- Hook: patch the `bl 0x15E5C` at orig 0x14DC8 -> MOUSE_T (0x3F8C0): call the original USB sender; if it does not return 1 (USB not ready) call ENTRY[6]=blehid_tx_stock(buf), which sends the 7-byte BLE report and returns 1 on success. USB wins when the cable is enumerated; otherwise BLE. Accumulators stay in stock hands, retried on the next pass if hvx refuses.
- The earlier nop patch @0x131D2 (motion pin gate) was dropped (stock behaviour kept).
- SD side finding: error-handler bkpt @0x284d4 (orig 0x74d4) = fault id 1 (SD assert) at SD pc 0x187CE seen while a debugger was attached; app IRQ 9 (TIMER1 tick) runs at NVIC priority 0 which the SD reserves -> candidate cause, TIMER1 priority should be >=2 after sd enable (live test showed 0 halts either way, unresolved).
- Built: out/s140_730_golden27000_ble.hex (blob 3014 B, ENTRY[7]). To test: flash, pair, move/click/scroll over BLE, expect smooth motion at the stock polling cadence; LOG[0x21] counts reports sent.

## UPDATE 10 — new probe (ST-Link V2) + stock-pipeline BLE transport flashed
- New debugger: ST-Link V2 (0483:3748, bcdDevice 1.00). pyocd `-t nrf52840` fails with "STLink error (29): Bad AP" (target class probes the CTRL-AP); `-t cortex_m` works. All debug scripts must use target_override 'cortex_m'. Flashing: work/nvmc_flash.py <hex> [--go] writes only 0x27000..0xFD000 through NVMC (diff per 4 KB page, verify, SYSRESETREQ); never touches SD/MBR, 0xFD000/0xFE000 or UICR.
- Flashed the stock-pipeline build (MOUSE_T hook at orig 0x14DC8, ENTRY[7]). Result over BLE with USB unplugged: 1883 reports in 26 s (~72/s), last hvx result 0, CFSR 0, g15 cursor moved (564 changes). USB cable enumerated => USB wins, BLE idle (by design).
- Pending user feedback: smoothness, buttons, wheel direction/behaviour. Possible follow-ups: report rate is bounded by the BLE connection interval (PPCP 7.5-15 ms) and the SD hvn tx queue size (default 1/event; raise via sd_ble_cfg_set BLE_CONN_CFG_GATTS hvn_tx_queue_size) and conn param request 7.5 ms; TIMER1 tick IRQ priority 0 vs SD reservation.

## UPDATE 11 — DPI-click reboot fixed (stock flash routines now use the SD flash API)
- Cause: stock settings-save routines orig 0xBE78 (erase) / 0xBED8 (write) use the SoftDevice flash API (svc 0x28/0x29, after svc 0x12 is_enabled) ONLY when the vendor mode var [0x20003003]==2; otherwise they write NVMC directly (0x11784 erase, 0x117B4 write). We run with the mode var = 1, so a DPI change (settings save to 0x8B000 page) wrote NVMC with the SD enabled -> SD memory-access fault -> app handler -> reset.
- Fix: patch the two `bne direct-NVMC` (orig 0xBE88 `13d1`, orig 0xBEEE `14d1`) to nop (mk_ble.py PATCHES). With the SD enabled they now go through sd_flash_*; with the SD off (dongle mode) svc 0x12 reports disabled and the direct path is still used. Flashed (page 0x2C000 only); user confirmed DPI clicks no longer reboot.
- IMPORTANT debugging lesson: halting the CPU makes the SoftDevice assert (id 1, SD pc 0x169CE/0x187CE) and the app handler then hits `bkpt` @0x284d4 / resets. All the "bkpt at 0x284d4" hits and resets seen while a debugger was attached were artifacts of my halts; do NOT infer faults from them. Debug without halting (memory reads, DWT/breakpoints only for short windows) and detach the probe for real-use tests. The earlier TIMER1-priority-0 suspicion is unproven (IRQ9 prio 0 left as is).

## UPDATE 12 — latency: BLE connection interval
- Windows (g15) connected at 15 ms (12 units) despite PPCP 7.5-15 ms. blehid now requests {min 6, max 6, latency 0, timeout 400} (7.5 ms) on BLE_GAP_EVT_CONNECTED and again at CONN_SEC_UPDATE if still slow (request_fast_conn). Verified from LOG: [0x30] initial=12, [0x31] after update=6 (7.5 ms), [0x32] latency=0, [0x33] request result 0. User: "slightly better".
- Measured throughput during continuous motion: ~415 reports/s accepted by the SD (several notifications per 7.5 ms connection event), last hvx result 0 => no backlog; stock polling/accumulation unchanged.
- Remaining latency is the BLE floor (<=7.5 ms to the next connection event, avg ~3.75 ms) plus the Windows HID/BLE stack. Not yet checked: stalls/bursts (add a failed-send counter), 2M PHY (sd_ble_gap_phy_update svc 0x8f already referenced), event length, hvn_tx_queue_size (RAM margin only 0x28 bytes below the app .data at 0x20003000 - raising SD RAM needs a smaller attr table).

## UPDATE 13 — mode switching verified with real buttons
- Stock facts: vendor mode var [0x20003003] is written only once (=1 at boot, orig 0xE880); mode 2 paths (SD flash API, 0x9084 sender, svc 0x33 system_off) exist but are unused by this product. USB vs radio is chosen per report by the USB-connected flag [0x200035DE]. The stock BLE strings ("Erase bonds!", Driver\app_ble.c) are only referenced by error paths: no reusable stock BLE app logic.
- Modes: USB = automatic whenever the cable is enumerated (USB sender succeeds first, BLE transport only on failure); BLE = default boot mode (SD on); 2.4G dongle = boot mode flag in config page 0xFE000 {C0DE0001, mode(1 BLE/2 DONGLE), ~mode, 0}, SD off, vendor radio init runs.
- Chord (default, baked in blehid.c): DPI P1.0 + BACK P0.9 + FORWARD P0.10 held ~3 s (RTC1 timing) toggles BLE <-> DONGLE, writes the config page and resets. Tested by hand: BLE -> chord -> DONGLE (config=2, LOG0=B1E0A002, SD flag 0, radio RX state, CFSR 0) -> chord -> BLE (reconnects to g15 with the stored bond, works). Known side effect: the DPI press also steps the DPI stage (stock handler) once per chord.
- Not verified: real 2.4G dongle link (no dongle available here); USB+BLE together (unplug/plug transitions); any LED/feedback for mode change; battery level over BLE (still fixed 100%).

## UPDATE 14 — mode feedback LED, battery level, release-on-leave, USB policy (all verified)
Backups: _backups/2026-10-25-ble-stable (before this update) and _backups/2026-10-25-ble-stable-v2 (after; hex, sources, full 1 MB flash incl. bond + config).
- LED feedback: stock RGB PWM0 (P0.13 R, P0.15 G, P0.17 B), stock duty buffer 0x20003270 (3 x u16, 0x8000|duty, 0x8000 = off). blehid overlays it from blehid_tick for a short pattern and restores the stock values: BLE boot = 2 blue blinks, dongle boot = 2 green blinks, BLE connect = 1 blue blink (300 ms on / 500 ms period, ~75% duty). Verified visually.
- Battery: stock battery.c percentage @0x20003076 (ADC avg -> lookup table, noisy for the first seconds after boot) published through BAS 0x2A19 only after being stable for ~3 s, notification on change. Windows shows the property {104EA319-...} 2 = 36 (matches stock).
- Release-all handling (stuck buttons across hosts): send_neutral() on mode switch, in leave_link() before the reset (+ clean sd_ble_gap_disconnect), when a host subscribes to the report CCCD, and when USB becomes active. Test with g15 button watcher: chord pressed at 38.24 s, Back/Forward released at 41.26 s = exactly at the switch (previously stuck for minutes).
- USB policy verified: BLE connected + cable enumerated -> USB owns the report (BLE sent 0 reports in 15 s of motion); unplug -> BLE resumes immediately (reports flow). USB first / BLE fallback comes from the MOUSE_T hook (USB sender tried first).
- g15 tools added: ble_battery.py (needs the device advertising; fails while Windows holds the link), battery.ps1 (reads Windows' battery property), btnwatch.py (+ winctl.sh btnwatch/btnout).

## UPDATE 15 — force re-pairing (verified by the user)
- Chord: LEFT P1.15 + RIGHT P1.13 + DPI P1.0 held ~3 s (BLE mode only, PAIR_P1_DEFAULT) -> pair_reset(): send release-all, write config page word3 (pairing generation, preserved by mode_switch) = gen+1, then (chained flash op) erase the bond record (0xFD000 <- zeros), leave_link(), reset. Boot with gen>0: sd_ble_gap_addr_set(random static = FICR DEVICEADDR low word XOR gen*0x9E3779B1, top bits 11) => hosts see a NEW device; the old host's stale pairing/key is never replayed (this is also why a stale Windows bond used to cause reconnect loops). LED: 3 purple blinks at the chord, 2 purple blinks at boot while unbonded (pairing mode), 2 blue when bonded.
- Verified: after the chord the LED blinked purple, g15 lost the old device, pairing with the new address worked; config word3 = 1, bond record rewritten by the new pairing, addr_set result 0.
- Notes: gen 0 keeps the factory FICR address (original bond/device identity). An old host entry stays in that host's Bluetooth list until removed there. Pairing is always possible (undirected adv, Just Works); a new host can also pair without the chord (it overwrites the single bond).
- Backups: _backups/2026-10-25-ble-stable-v3 (hex + sources). Stuck key after mode switch was Windows Explorer's own input state (ctrl-alt-del -> exit explorer cleared it), not the mouse; the release-all report is still sent and harmless.

## UPDATE 16 — BLE power optimization (verified on hardware; backup _backups/2026-10-26-ble-stable-v4-power)
Findings (non-halting reads): the 32 MHz crystal (HFXO) was selected 100% of the time while connected+idle; the stock firmware starts it directly at boot (before the SD exists), so the SD never owned/stopped it. Stock also keeps TIMER1 (1 kHz tick) and PWM0 (LED, even when off) running => HFINT stays on (HF clock "running" 100% is HFINT, not HFXO: look at HFCLKSTAT bit0 for the source).
Changes:
1. HFXO takeover: after 3 s with no USB, blehid_tick does sd_clock_hfclk_request()+sd_clock_hfclk_release() (SD takes ownership and stops it) and releases the stray boot-time count of the stock driver (nrf_drv_clock_hfclk_release, orig 0xF9A0, count @0x20007C08) so a later USB attach (count 0->1) really requests the crystal. Verified: BLE idle HFXO 0%; USB attached HFXO 100%; unplug -> 0%, replug -> 100%, enumerates cleanly, USB works.
2. Idle link: 5 s without a report -> conn param update {15 ms, latency 20, 4 s timeout}; first report requests {7.5 ms, latency 0} again. Windows accepts (granted 12/20 after idle, back to 6/0 about a second after motion starts). Needed the notify flag to be set on bonded reconnect (CCCD restored via sys_attr_set).
3. Advertising: 50 ms for 30 s after boot/disconnect, then 500 ms (adv_restart; BLE_GAP_EVT_ADV_SET_TERMINATED).
4. Stock idle sleep (counter @0x20003048 +1/s, threshold u16 @0x200038CB = 420 s) now really reaches System OFF with the SD on: the stock sleep prep (orig 0xAB98) tore the radio down (0x15B70/0x18B24 -> NVIC/RADIO writes) which faults (SD id 0x1001, caught at the app fault handler 0x28474) and reset the chip, and then wrote POWER directly. Patched: both radio calls gated on SD off (RADIO_A_T/RADIO_B_T), `cmp/beq` at orig 0xABA0 -> SYSOFF_T (SD on: blehid_before_sleep = release-all + clean disconnect, then falls into svc 0x33 sd_power_system_off; SD off: original direct path). Verified with the probe idle: mouse sleeps (g15 loses it, no reboot), a button press wakes it (2 blue blinks) and BLE reconnects.
Debug hooks left in blehid: LOG[0x38]/[0x39]/[0x3B] = idle interval/latency/timeout override, LOG[0x3A]=1 forces the idle request; LOG[0x40..0x42] persistent before-sleep counters. Testing note: with a debugger attached System OFF is only emulated; arm the sleep timer by writing u16 @0x200038CB (RAM only) and release the probe.
Not done (bigger, riskier): stopping TIMER1 tick / PWM0 when idle; LED PWM keeps HFINT running.
