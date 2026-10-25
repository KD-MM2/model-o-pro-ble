#!/usr/bin/env python3
"""mk_ble.py — BLE patch for the relocated golden app (base 0x27000). Builds build/s140_730_golden27000_ble.hex.

Flash map additions: STUB 0x3F000 (asm: SD bring-up), THUNK 0x3F800 (main-loop poll hook), BLOB 0x40000 (blehid.c).
Hooks in the app (orig addr -> reloc = +0x21000):
  0xE878 bl app_usbd_init-wrapper(0x6F68)  -> bl STUB   (stub does SD bring-up, then tail-calls 0x6F68)
  0xE92C bl 0x14AE4 (end of main loop)     -> bl THUNK  (thunk calls blehid_poll, then tail-calls 0x14AE4)
Patches: 0x6F94 DCDCEN direct write -> svc #0x3f ; 0xE88A skip vendor 2.4G radio init.
Stub steps: app_sched init, nrf_drv_power_init, nrf_sdh_enable_request, sd_ble_cfg_set x2, sd_ble_enable, blehid_init().
Log @0x2003F000: [4]power_init [8]sdh_enable [0xc]cfg attr [0x10]cfg vs [0x14]ble_enable [0x18]ram end [0x1c]blehid_init ret [0x24]done.
"""
import struct, sys
from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from intelhex import IntelHex

D = 0x21000
APP_BASE = 0x27000
STUB, THUNK, BLOB = 0x3F000, 0x3F800, 0x40000
LOG = 0x2003F000
HOOK1 = 0xE878 + D
HOOK2 = 0xE92C + D
ORIG1 = 0x6F68 + D
ORIG2 = 0x14AE4 + D
POWER_INIT = 0xFB0C + D
SDH_ENABLE = 0x11C18 + D
SCHED = 0x20003704
SCHED_HDR = 0x2000B000
SCHED_DAT = 0x2000B100
RAM_BASE = 0x20003000
ATTR_TAB = int(sys.argv[1], 0) if len(sys.argv) > 1 else 720
VS_UUID = 0
import os
PUMP = int(os.environ.get('PUMP', '0'))

ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)

blob = open('build/blehid.bin', 'rb').read()
init_addr, poll_addr, send_addr, state_addr, nosd_addr, chord_addr, txstock_addr, sleep_addr = struct.unpack_from('<8I', blob, 0)

CFG = 0xFE000
stub_asm = f"""
    push {{r4-r7, lr}}
    movw r0, #{CFG & 0xFFFF}
    movt r0, #{CFG >> 16}
    ldr r1, [r0]
    movw r2, #0x0001
    movt r2, #0xC0DE
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
    movw r0, #{BLOB & 0xFFFF}
    movt r0, #{BLOB >> 16}
    ldr r0, [r0, #16]
    blx r0
    pop {{r4-r7, lr}}
    b.w #{ORIG1}
ble_mode:
    sub sp, #0x20
    movw r4, #{LOG & 0xFFFF}
    movt r4, #{LOG >> 16}
    movs r0, #0
    mov r2, r4
    movs r1, #16
clr:
    str r0, [r2], #4
    subs r1, #1
    bne clr
    movw r0, #0x0001
    movt r0, #0xB1E0
    str r0, [r4]
    movw r0, #{SCHED & 0xFFFF}
    movt r0, #{SCHED >> 16}
    movs r1, #0
    strb r1, [r0]
    strb r1, [r0, #1]
    movs r1, #16
    strh r1, [r0, #2]
    movs r1, #15
    strh r1, [r0, #4]
    movw r1, #{SCHED_HDR & 0xFFFF}
    movt r1, #{SCHED_HDR >> 16}
    str r1, [r0, #8]
    movw r1, #{SCHED_DAT & 0xFFFF}
    movt r1, #{SCHED_DAT >> 16}
    str r1, [r0, #0xc]
    movw r6, #{RAM_BASE & 0xFFFF}
    movt r6, #{RAM_BASE >> 16}
    movs r0, #0
    bl #{POWER_INIT}
    str r0, [r4, #4]
    bl #{SDH_ENABLE}
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
    movs r1, #{VS_UUID}
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
    movw r1, #0x3833
    movt r1, #0x2000
    movs r0, #{PUMP}
    strb r0, [r1]
    movw r0, #{BLOB & 0xFFFF}
    movt r0, #{BLOB >> 16}
    ldr r0, [r0]
    blx r0
    str r0, [r4, #0x1c]
done:
    movw r0, #0xFFFF
    movt r0, #0xB1E0
    str r0, [r4, #0x24]
    add sp, #0x20
    pop {{r4-r7, lr}}
    b.w #{ORIG1}
"""
stub = bytes(ks.asm(stub_asm, STUB)[0])
thunk_asm = f"""
    push {{r4, lr}}
    movw r0, #{(BLOB + 4) & 0xFFFF}
    movt r0, #{(BLOB + 4) >> 16}
    ldr r0, [r0]
    blx r0
    pop {{r4, pc}}
"""
thunk = bytes(ks.asm(thunk_asm, THUNK)[0])
DCDC_T, GATE_T, MOUSE_T, SYSOFF_T, RADIO_A_T, RADIO_B_T = 0x3F840, 0x3F880, 0x3F8C0, 0x3F900, 0x3F940, 0x3F960
USB_SEND = 0x15E5C + D
dcdc_asm = """
    movw r1, #0x3830
    movt r1, #0x2000
    ldrb r1, [r1]
    cbz r1, direct
    movs r0, #1
    svc #0x3f
    bx lr
direct:
    movw r1, #0x0578
    movt r1, #0x4000
    movs r0, #1
    str r0, [r1]
    bx lr
"""
dcdc_t = bytes(ks.asm(dcdc_asm, DCDC_T)[0])
gate_asm = f"""
    movw r1, #0x3830
    movt r1, #0x2000
    ldrb r1, [r1]
    cbnz r1, skip
    cmp r0, #1
    bne skip
    bx lr
skip:
    movw r1, #{((0xE894 + D) | 1) & 0xFFFF}
    movt r1, #{((0xE894 + D) | 1) >> 16}
    bx r1
"""
gate_t = bytes(ks.asm(gate_asm, GATE_T)[0])
mouse_asm = f"""
    push {{r4, lr}}
    mov r4, r0
    bl #{USB_SEND}
    cmp r0, #1
    beq done
    movw r1, #{BLOB & 0xFFFF}
    movt r1, #{BLOB >> 16}
    ldr r1, [r1, #24]
    mov r0, r4
    blx r1
done:
    pop {{r4, pc}}
"""
mouse_t = bytes(ks.asm(mouse_asm, MOUSE_T)[0])
# stock idle->System OFF path (orig 0xAB98): `cmp r0,#1; beq direct SYSTEMOFF` -> bl SYSOFF_T. With the SD on the direct POWER
# register write would fault, so leave the host cleanly and fall through to svc 0x33 (sd_power_system_off); with the SD off
# (dongle mode) jump to the original direct path.
sysoff_asm = f"""
    movw r1, #0x3830
    movt r1, #0x2000
    ldrb r1, [r1]
    cbz r1, direct
    push {{r4, lr}}
    movw r0, #{BLOB & 0xFFFF}
    movt r0, #{BLOB >> 16}
    ldr r0, [r0, #28]
    blx r0
    pop {{r4, lr}}
    bx lr
direct:
    movw r1, #{((0xABAE + D) | 1) & 0xFFFF}
    movt r1, #{((0xABAE + D) | 1) >> 16}
    bx r1
"""
sysoff_t = bytes(ks.asm(sysoff_asm, SYSOFF_T)[0])
# stock sleep preparation tears the 2.4G radio down (orig 0x15B70, 0x18B24) with direct NVIC/RADIO writes: that faults with the
# SD enabled (APP_MEMACC), so run them only when the SD is off
def radio_gate(target_orig):
    return f"""
    movw r1, #0x3830
    movt r1, #0x2000
    ldrb r1, [r1]
    cbnz r1, skip
    movw r1, #{((target_orig + D) | 1) & 0xFFFF}
    movt r1, #{((target_orig + D) | 1) >> 16}
    bx r1
skip:
    bx lr
"""
radio_a_t = bytes(ks.asm(radio_gate(0x15B70), RADIO_A_T)[0])
radio_b_t = bytes(ks.asm(radio_gate(0x18B24), RADIO_B_T)[0])
assert STUB + len(stub) < THUNK and THUNK + len(thunk) < DCDC_T and DCDC_T + len(dcdc_t) < GATE_T and GATE_T + len(gate_t) < MOUSE_T and MOUSE_T + len(mouse_t) < SYSOFF_T and SYSOFF_T + len(sysoff_t) < RADIO_A_T and RADIO_A_T + len(radio_a_t) < RADIO_B_T and RADIO_B_T + len(radio_b_t) < BLOB, (len(stub), len(thunk))

app = bytearray(open('build/golden_app_27000.bin', 'rb').read())
import os
HOOKS = [(HOOK1, ORIG1, STUB)] + ([] if os.environ.get('NOPOLL') else [(HOOK2, ORIG2, THUNK)])
for hook, orig, tgt in HOOKS:
    o = hook - APP_BASE
    assert bytes(app[o:o + 4]) == bytes(ks.asm(f'bl #{orig}', hook)[0]), hex(hook)
    app[o:o + 4] = bytes(ks.asm(f'bl #{tgt}', hook)[0])

PATCHES = [  # (orig_addr, expected, new)
    (0x6F94, '07490860', bytes(ks.asm(f'bl #{DCDC_T}', 0x6F94 + D)[0]).hex()),   # direct DCDCEN write -> thunk (svc 0x3f when the SD is on)
    (0xE888, '012803d1', bytes(ks.asm(f'bl #{GATE_T}', 0xE888 + D)[0]).hex()),   # cmp r0,#1; bne -> gate: skip vendor 2.4G radio init when the SD is on
    (0x14DC8, bytes(ks.asm(f'bl #{USB_SEND}', 0x14DC8 + D)[0]).hex(), bytes(ks.asm(f'bl #{MOUSE_T}', 0x14DC8 + D)[0]).hex()),   # stock mouse report builder (0x14CEC): USB transport call -> try USB, else BLE
    (0xABA0, '012804d0', bytes(ks.asm(f'bl #{SYSOFF_T}', 0xABA0 + D)[0]).hex()),   # idle -> System OFF: SD-safe via svc 0x33 (thunk keeps the direct path when the SD is off)
    (0xABDA, bytes(ks.asm(f'bl #{0x15B70 + D}', 0xABDA + D)[0]).hex(), bytes(ks.asm(f'bl #{RADIO_A_T}', 0xABDA + D)[0]).hex()),   # sleep prep: radio teardown only when the SD is off
    (0xABDE, bytes(ks.asm(f'bl #{0x18B24 + D}', 0xABDE + D)[0]).hex(), bytes(ks.asm(f'bl #{RADIO_B_T}', 0xABDE + D)[0]).hex()),
    (0xBE88, '13d1', '00bf'),   # flash erase: `bne direct-NVMC` (taken unless vendor mode var==2) -> nop: use sd_flash_page_erase whenever the SD is enabled
    (0xBEEE, '14d1', '00bf'),   # flash write: same for sd_flash_write
]
for oa, exp_hex, new_hex in PATCHES:
    po = oa + D - APP_BASE
    assert app[po:po + len(exp_hex) // 2].hex() == exp_hex, (hex(oa), app[po:po + 4].hex())
    app[po:po + len(new_hex) // 2] = bytes.fromhex(new_hex)

sd = IntelHex('vendor/s140_nrf52_7.3.0_softdevice.hex')
ih = IntelHex()
ih.merge(sd)
for i, b in enumerate(app): ih[APP_BASE + i] = b
for i, b in enumerate(stub): ih[STUB + i] = b
for i, b in enumerate(thunk): ih[THUNK + i] = b
for i, b in enumerate(dcdc_t): ih[DCDC_T + i] = b
for i, b in enumerate(gate_t): ih[GATE_T + i] = b
for i, b in enumerate(mouse_t): ih[MOUSE_T + i] = b
for i, b in enumerate(sysoff_t): ih[SYSOFF_T + i] = b
for i, b in enumerate(radio_a_t): ih[RADIO_A_T + i] = b
for i, b in enumerate(radio_b_t): ih[RADIO_B_T + i] = b
for i, b in enumerate(blob): ih[BLOB + i] = b
ih.write_hex_file('build/s140_730_golden27000_ble.hex')
open('build/golden_app_27000_ble.bin', 'wb').write(app)
print('stub', len(stub), 'thunk', len(thunk), 'blob', len(blob), 'attr_tab', ATTR_TAB, 'init', hex(init_addr), 'poll', hex(poll_addr), 'send', hex(send_addr), 'state', hex(state_addr))
print('hex', hex(ih.minaddr()), hex(ih.maxaddr()))
