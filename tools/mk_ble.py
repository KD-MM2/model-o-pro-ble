#!/usr/bin/env python3
"""mk_ble.py [attr_table_size] -- assemble the final image build/s140_730_golden27000_ble.hex from
  vendor/s140_nrf52_7.3.0_softdevice.hex   MBR + SoftDevice S140 7.3.0      0x00000..0x26FFF
  build/golden_app_27000.bin               stock app, relocated (+0x21000)  0x27000..0x3E206
  STUB / THUNK / compatibility thunks      generated here                   0x3F000..
  build/blehid.bin                         BLE module (fw/blehid)           0x40000..

The stock app is changed at the sites in PATCHES only. Each entry asserts the original bytes first, so a different stock
version stops the build instead of producing a broken image. Addresses in comments are "orig" addresses (stock app linked
at 0x6000); the relocated code lives at orig + 0x21000.

Two kinds of changes:
  * hooks that add BLE (boot stub, main-loop thunk, mouse-report routing);
  * SoftDevice compatibility: with the SoftDevice enabled it owns POWER, NVMC, RADIO, TIMER0 and their interrupts, and a
    direct access from the app is a fault (error 0x1001, APP_MEMACC). Every such stock site gets a thunk that keeps the
    stock code when the SoftDevice is off (RF mode = stock behaviour) and skips it or uses the SoftDevice API when it is on.
SD flag = byte 0x20003830, set by the stock nrf_sdh library when the SoftDevice is enabled (BLE mode only).
"""
import struct, sys
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from intelhex import IntelHex

D = 0x21000                       # relocation offset: orig -> reloc
APP_BASE = 0x27000
STUB, THUNKS, BLOB = 0x3F000, 0x3F800, 0x40000
ATTR_TAB = int(sys.argv[1], 0) if len(sys.argv) > 1 else 720   # GATT attribute table size given to the SoftDevice
STUB_LOG = 0x2003F000             # [4] power_init [8] sdh_enable [0xC] cfg attr [0x10] cfg uuid [0x14] ble_enable [0x18] app RAM [0x1C] blehid_init [0x24] done
CFG = 0xF6000                     # config record (see fw/blehid/blehid.c): magic, mode, ~mode, generation
SD_FLAG = 0x20003830

ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
def asm(src, addr): return bytes(ks.asm(src, addr)[0])
def reloc(orig): return orig + D
def thumb(addr): return addr | 1
def movw_movt(reg, value): return f"movw {reg}, #{value & 0xFFFF}\n    movt {reg}, #{value >> 16}"

blob = open('build/blehid.bin', 'rb').read()
E_INIT, E_TICK, E_INIT_RF, E_REPORT = (BLOB + 4 * i for i in range(4))   # ENTRY[] slots in the blob (addresses of the pointers)

# ---------------------------------------------------------------------------------------------------------------------------
# Boot stub. STOCK: orig 0xE878 calls 0x6F68 (USB / app init) during start-up. MOD: the call goes here first.
#   config record says RF -> blehid_init_nosd() (mode chord + LED only), then the stock init as shipped.
#   otherwise (BLE)       -> enable the SoftDevice with stock library functions, call blehid_init(), then the stock init.
# app_scheduler: the stock nrf_sdh library (linked in, never used by the product) passes SoftDevice events through
# app_scheduler, which the product never initialises; the stub sets up its state (16 events, buffers at 0x2000B000/B100).
# 0x20003833: nrf_sdh BLE-event poller gate, kept 0 so the stock library never consumes BLE events (blehid polls them).
stub_src = f"""
    push {{r4-r7, lr}}
    {movw_movt('r0', CFG)}
    ldr r1, [r0]
    {movw_movt('r2', 0xC0DE0001)}
    cmp r1, r2
    bne.w ble_mode
    ldr r1, [r0, #4]
    ldr r2, [r0, #8]
    eors r2, r1
    mvns r2, r2
    cmp r2, #0
    bne.w ble_mode
    cmp r1, #2
    bne.w ble_mode
    {movw_movt('r0', E_INIT_RF)}
    ldr r0, [r0]
    blx r0
    pop {{r4-r7, lr}}
    b.w #{reloc(0x6F68)}
ble_mode:
    sub sp, #0x20
    {movw_movt('r4', STUB_LOG)}
    movs r0, #0
    mov r2, r4
    movs r1, #16
clear_log:
    str r0, [r2], #4
    subs r1, #1
    bne clear_log
    {movw_movt('r0', 0xB1E00001)}
    str r0, [r4]
    {movw_movt('r0', 0x20003704)}
    movs r1, #0
    strb r1, [r0]
    strb r1, [r0, #1]
    movs r1, #16
    strh r1, [r0, #2]
    movs r1, #15
    strh r1, [r0, #4]
    {movw_movt('r1', 0x2000B000)}
    str r1, [r0, #8]
    {movw_movt('r1', 0x2000B100)}
    str r1, [r0, #0xc]
    {movw_movt('r6', 0x20003000)}
    movs r0, #0
    bl #{reloc(0xFB0C)}
    str r0, [r4, #4]
    bl #{reloc(0x11C18)}
    str r0, [r4, #8]
    cmp r0, #0
    bne.w done
    movw r1, #{ATTR_TAB}
    str r1, [sp, #8]
    movs r0, #0xA1
    add r1, sp, #8
    mov r2, r6
    svc #0x69
    str r0, [r4, #0xc]
    movs r1, #0
    strb r1, [sp, #0xc]
    movs r0, #1
    add r1, sp, #0xc
    mov r2, r6
    svc #0x69
    str r0, [r4, #0x10]
    str r6, [sp, #4]
    add r0, sp, #4
    svc #0x60
    str r0, [r4, #0x14]
    ldr r1, [sp, #4]
    str r1, [r4, #0x18]
    cmp r0, #0
    bne.w done
    {movw_movt('r1', 0x20003833)}
    movs r0, #0
    strb r0, [r1]
    {movw_movt('r0', E_INIT)}
    ldr r0, [r0]
    blx r0
    str r0, [r4, #0x1c]
done:
    {movw_movt('r0', 0xB1E0FFFF)}
    str r0, [r4, #0x24]
    add sp, #0x20
    pop {{r4-r7, lr}}
    b.w #{reloc(0x6F68)}
"""
# Steps above: nrf_drv_power_init(NULL) (orig 0xFB0C), nrf_sdh_enable_request() (orig 0x11C18, sets the SD flag),
# sd_ble_cfg_set(BLE_GATTS_CFG_ATTR_TAB_SIZE, ATTR_TAB) and sd_ble_cfg_set(BLE_COMMON_CFG_VS_UUID, 0) (svc 0x69),
# sd_ble_enable(&app_ram_base = 0x20003000) (svc 0x60), blehid_init().

# ---------------------------------------------------------------------------------------------------------------------------
# Thunks, laid out one after the other from THUNKS. Each returns into the stock code exactly where the stock code would go.
# Scratch registers: r12 where the patched instruction was a call (r0-r3 may be arguments, r12 is free at a call),
# r0/r1 where the patched instructions were not a call (checked dead at those sites).
thunk_src = {}

# Main loop. STOCK: orig 0xE92C `bl 0x14AE4` (report-flag builder) at the end of each main-loop pass.
# MOD: call blehid_tick(), which runs 0x14AE4 itself and then the BLE work.
thunk_src['TICK'] = f"""
    push {{r4, lr}}
    {movw_movt('r0', E_TICK)}
    ldr r0, [r0]
    blx r0
    pop {{r4, pc}}
"""

# DC/DC regulator. STOCK: orig 0x6F92 `movs r0,#1` then 0x6F94 `ldr r1,=0x40000578; str r0,[r1]` = POWER.DCDCEN = 1.
# MOD: SD on -> sd_power_dcdc_mode_set(1) (svc 0x3F, same effect through the owner of POWER); SD off -> the stock store.
# r0 is restored to 1 so the function returns exactly what the stock code returned.
thunk_src['DCDC'] = f"""
    {movw_movt('r1', SD_FLAG)}
    ldrb r1, [r1]
    cbz r1, stock
    push {{r0, lr}}
    svc #0x3f
    pop {{r0, pc}}
stock:
    {movw_movt('r1', 0x40000578)}
    str r0, [r1]
    bx lr
"""

# 2.4 GHz radio start at boot. STOCK: orig 0xE87E..0xE888 sets the mode var [0x20003003] = 1, calls 0x78A8 (which clears it
# when USB is present), then `cmp r0,#1; bne 0xE894`: still 1 -> 0x15A1C (radio power-up) and 0x18AD0 (TIMER0 setup).
# MOD: SD on -> always skip to 0xE894 (the SoftDevice owns RADIO and TIMER0); SD off -> the stock test.
thunk_src['GATE'] = f"""
    {movw_movt('r1', SD_FLAG)}
    ldrb r1, [r1]
    cbnz r1, skip
    cmp r0, #1
    bne skip
    bx lr
skip:
    {movw_movt('r1', thumb(reloc(0xE894)))}
    bx r1
"""

# Idle sleep. STOCK: after the idle timeout (420 s) orig 0xAB9C loads the mode var, then `cmp r0,#1; beq 0xABAE`:
# 1 (on battery) -> write POWER.SYSTEMOFF directly (0xABAE); otherwise svc 0x33 sd_power_system_off (0xABA4).
# MOD: SD on -> continue at 0xABA4 (svc 0x33: the SoftDevice turns the chip off; the direct write would fault);
# SD off -> the stock test. Wake-up is a reset, as in stock.
thunk_src['SYSOFF'] = f"""
    {movw_movt('r1', SD_FLAG)}
    ldrb r1, [r1]
    cbnz r1, sd_path
    cmp r0, #1
    beq direct
sd_path:
    bx lr
direct:
    {movw_movt('r1', thumb(reloc(0xABAE)))}
    bx r1
"""

# Calls into the stock 2.4 GHz radio code (direct RADIO / TIMER0 / NVIC access). SD on -> skip (return), SD off -> the call.
def radio_gate(target_orig):
    return f"""
    {movw_movt('r12', SD_FLAG)}
    ldrb.w r12, [r12]
    cmp.w r12, #0
    bne skip
    {movw_movt('r12', thumb(reloc(target_orig)))}
    bx r12
skip:
    bx lr
"""
thunk_src['RADIO_15B70'] = radio_gate(0x15B70)   # radio teardown
thunk_src['RADIO_18B24'] = radio_gate(0x18B24)   # radio timer stop (sleep preparation)
thunk_src['RADIO_15A1C'] = radio_gate(0x15A1C)   # radio power-up
thunk_src['RADIO_18AD0'] = radio_gate(0x18AD0)   # TIMER0 setup for the 2.4 GHz link
thunk_src['RADIO_16740'] = radio_gate(0x16740)   # radio start with new wireless parameters

# Mouse report routing. STOCK: the report builder (orig 0x14CEC) picks the transport for the mouse report at 0x14D68:
#   `ldrb r0,[r4]; cmp r0,#1; beq 0x14D7A` with r4 = 0x200035DE (USB enumerated flag): 1 -> USB send (0x84BA);
#   else by the mode var [0x20003003] (r7): 1 -> 2.4 GHz queue (0x15E5C), 2 -> 0x9084 (unused), else nothing.
#   After a send: accepted -> 0x14DE0 (clear the X/Y/wheel/pan accumulators and the "report due" flag), busy -> 0x14DF8.
# MOD: SD on -> blehid_tx_stock(0x200035E5 = r4 + 7, the report buffer) and continue at 0x14DE0 / 0x14DF8 like the stock
#   senders, never USB or 2.4 GHz (a cable only charges in BLE mode); SD off -> the stock instructions, flags intact.
# Only the mouse report is routed; the other report types of this builder (keyboard/media from button remaps) keep the
# stock routing and are not carried over BLE.
thunk_src['REPORT'] = f"""
    {movw_movt('r0', SD_FLAG)}
    ldrb r0, [r0]
    cbnz r0, ble
    ldrb r0, [r4]
    cmp r0, #1
    bx lr
ble:
    adds r0, r4, #7
    {movw_movt('r1', E_REPORT)}
    ldr r1, [r1]
    blx r1
    cmp r0, #1
    beq sent
    {movw_movt('r1', thumb(reloc(0x14DF8)))}
    bx r1
sent:
    {movw_movt('r1', thumb(reloc(0x14DE0)))}
    bx r1
"""

thunk_addr, thunk_bin, at = {}, {}, THUNKS
for name, src in thunk_src.items():
    thunk_addr[name] = at
    thunk_bin[name] = asm(src, at)
    at = (at + len(thunk_bin[name]) + 0x1F) & ~0x1F
assert at <= BLOB, 'thunks overlap the blob'
stub = asm(stub_src, STUB)
assert STUB + len(stub) <= THUNKS, 'stub overlaps the thunks'

def bl(orig, target):  return asm(f'bl #{target}', reloc(orig)).hex()
def bw(orig, target):  return asm(f'b.w #{target}', reloc(orig)).hex()
T = thunk_addr

# (orig address, original bytes, new bytes, why)
PATCHES = [
    (0xE878, bl(0xE878, reloc(0x6F68)), bl(0xE878, STUB), 'boot: SoftDevice bring-up / RF-mode init before the stock USB/app init'),
    (0xE92C, bl(0xE92C, reloc(0x14AE4)), bl(0xE92C, T['TICK']), 'main loop: blehid_tick (runs the stock 0x14AE4 first)'),
    (0x6F94, '07490860', bl(0x6F94, T['DCDC']), 'POWER.DCDCEN: via the SoftDevice when it is on'),
    (0xE888, '012803d1', bl(0xE888, T['GATE']), 'boot: no 2.4 GHz radio start when the SoftDevice is on'),
    (0xABA0, '012804d0', bl(0xABA0, T['SYSOFF']), 'idle sleep: System OFF through the SoftDevice when it is on'),
    (0xABDA, bl(0xABDA, reloc(0x15B70)), bl(0xABDA, T['RADIO_15B70']), 'sleep preparation: radio teardown only with the SoftDevice off'),
    (0xABDE, bl(0xABDE, reloc(0x18B24)), bl(0xABDE, T['RADIO_18B24']), 'sleep preparation: radio timer stop only with the SoftDevice off'),
    (0x19B84, bl(0x19B84, reloc(0x15A1C)), bl(0x19B84, T['RADIO_15A1C']), '2.4 GHz link state machine, USB removed: radio power-up only with the SoftDevice off (the mode-var update before it stays)'),
    (0x19B8C, bw(0x19B8C, reloc(0x18AD0)), bw(0x19B8C, T['RADIO_18AD0']), 'same case, tail call: TIMER0 setup only with the SoftDevice off'),
    (0x19B0E, bw(0x19B0E, reloc(0x15B70)), bw(0x19B0E, T['RADIO_15B70']), 'same state machine, other event, tail call: radio teardown only with the SoftDevice off'),
    (0x14880, bl(0x14880, reloc(0x16740)), bl(0x14880, T['RADIO_16740']), 'vendor command 0xA0 (wireless parameters, sent by Glorious CORE): radio restart only with the SoftDevice off'),
    # Flash erase / write of the stock settings (DPI etc.). STOCK: `if (mode var == 2) { svc 0x12 sd_softdevice_is_enabled;
    # enabled -> sd_flash_* }`, every other case writes the NVMC directly (a fault with the SoftDevice on: the DPI click reboot).
    # MOD: the `bne` over the mode-2 test becomes a nop, so the stock code always asks svc 0x12: SoftDevice on -> sd_flash_*,
    # off -> the direct NVMC path as before.
    (0xBE88, '13d1', '00bf', 'settings flash erase: ask the SoftDevice whether it is enabled (stock mode-2 path) in every mode'),
    (0xBEEE, '14d1', '00bf', 'settings flash write: same'),
    (0x14D68, '20780128', bl(0x14D68, T['REPORT']), 'mouse report: BLE only when the SoftDevice is on'),
]

app = bytearray(open('build/golden_app_27000.bin', 'rb').read())
for orig, old, new, why in PATCHES:
    o = reloc(orig) - APP_BASE
    have = app[o:o + len(old) // 2].hex()
    assert have == old, 'orig 0x%X: expected %s, found %s (different stock version?)' % (orig, old, have)
    assert len(new) == len(old)
    app[o:o + len(new) // 2] = bytes.fromhex(new)

ih = IntelHex()
ih.merge(IntelHex('vendor/s140_nrf52_7.3.0_softdevice.hex'))
for base, data in [(APP_BASE, app), (STUB, stub), (BLOB, blob)] + [(T[n], thunk_bin[n]) for n in thunk_bin]:
    for i, b in enumerate(data): ih[base + i] = b
ih.write_hex_file('build/s140_730_golden27000_ble.hex')
print('patches %d, stub %d B, thunks %s, blob %d B (entry %s)' % (len(PATCHES), len(stub),
      ' '.join('%s@%X' % (n, T[n]) for n in T), len(blob), ' '.join('%X' % v for v in struct.unpack_from('<4I', blob, 0))))
print('hex 0x%X..0x%X' % (ih.minaddr(), ih.maxaddr()))
