#!/usr/bin/env python3
"""mk_bootloader.py KEY.pem -- build the Nordic secure BLE DFU bootloader for this mouse -> build/bootloader.hex

The bootloader is Nordic's example, used as shipped except for the changes listed in this file:
    nRF5 SDK 17.1.0, examples/dfu/secure_bootloader/pca10056_s140_ble  (main.c, sdk_config.h, armgcc/Makefile)
The script copies the example's armgcc Makefile and two source files into build/bootloader/, applies the changes below
(each one asserts the original text first, so a different SDK stops the build instead of producing something else), and
runs make with Arm GCC 10.3. The public half of KEY.pem is compiled in: the bootloader accepts only update packages
signed with that key (tools/mk_dfu.py signs them).

What the bootloader does on this mouse (all stock Nordic behaviour unless marked MOD):
  * lives at 0xF8000-0xFDFFF; the MBR starts it because word 0xFF8 of the MBR page holds 0xF8000 (MBR 2.4.x reads that
    word before UICR.BOOTLOADERADDR, so UICR is never written; tools/install_bootloader.py writes the word);
  * every boot: checks the app (CRC from the settings page 0xFF000, skipped after a wake from System OFF), then starts
    it through the SoftDevice exactly as the MBR would without a bootloader;
  * stays in DFU mode (BLE, advertising "ModelO DFU") when: the app is not valid, GPREGRET = 0xB1 (the app's DFU chord),
    or the DPI button is held for 2 s at boot (MOD: stock = pressed at the instant of boot);
  * DFU is dual bank: the new image is received above the current one and copied over it only after its signature
    and hash check passed; the app data area 0xF5000-0xF7FFF (bond and config records) is never erased.
"""
import os, subprocess, sys
from intelhex import IntelHex

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SDK = os.path.join(ROOT, 'vendor/nRF5_SDK_17.1.0_ddde560')
EXAMPLE = os.path.join(SDK, 'examples/dfu/secure_bootloader')
GCC_BIN = os.path.join(ROOT, 'vendor/gcc-arm-none-eabi-10.3-2021.10/bin/')
OUT = os.path.join(ROOT, 'build/bootloader')
KEY = os.path.abspath(sys.argv[1])
BL_START, BL_END = 0xF8000, 0xFE000

def patch(text, old, new, what):
    assert text.count(old) == 1, 'SDK text not found exactly once (%s): %r' % (what, old[:60])
    return text.replace(old, new)

os.makedirs(OUT, exist_ok=True)
assert os.path.isfile(KEY), 'signing key %s missing: run `make dfu-key` once (and back the key up)' % KEY

# ---- public key: the C array the bootloader verifies packages with
subprocess.check_call([os.path.join(ROOT, 'tools/nrfutil'), 'keys', 'display', '--key', 'pk', '--format', 'code', KEY,
                       '--out_file', os.path.join(OUT, 'dfu_public_key.c')])

# ---- main.c: DFU event observer
# STOCK: lights the devkit LEDs (P0.13-P0.16) on DFU events.  MOD: does nothing; this mouse has other circuits on those pins.
src = open(os.path.join(EXAMPLE, 'main.c')).read()
src = patch(src, '''static void dfu_observer(nrf_dfu_evt_type_t evt_type)
{
    switch (evt_type)
    {
        case NRF_DFU_EVT_DFU_FAILED:
        case NRF_DFU_EVT_DFU_ABORTED:
        case NRF_DFU_EVT_DFU_INITIALIZED:
            bsp_board_init(BSP_INIT_LEDS);
            bsp_board_led_on(BSP_BOARD_LED_0);
            bsp_board_led_on(BSP_BOARD_LED_1);
            bsp_board_led_off(BSP_BOARD_LED_2);
            break;
        case NRF_DFU_EVT_TRANSPORT_ACTIVATED:
            bsp_board_led_off(BSP_BOARD_LED_1);
            bsp_board_led_on(BSP_BOARD_LED_2);
            break;
        case NRF_DFU_EVT_DFU_STARTED:
            break;
        default:
            break;
    }
}''', '''/* MOD (Glorious Model O Pro): STOCK drives the PCA10056 devkit LEDs here. This mouse has no LEDs on those pins,
 * so the bootloader must not drive them: the observer does nothing. */
static void dfu_observer(nrf_dfu_evt_type_t evt_type)
{
    (void)evt_type;
}''', 'main.c dfu_observer')
open(os.path.join(OUT, 'main.c'), 'w').write(src)

# ---- nrf_bootloader.c: DFU button
# STOCK: DFU mode if the button reads low once at boot.
# MOD:   the button must stay low for DFU_BUTTON_HOLD_MS. Every button of this mouse wakes it from System OFF (stock
#        sleep code orig 0xABF6..0xAC38 arms SENSE on all of them) and that wake-up is a reset, so the wake-up click would
#        otherwise put the mouse in DFU mode. A click is released long before 2 s and costs only its own duration.
#        While it waits, the loop feeds the watchdog: the stock firmware runs the WDT with a 2.0 s timeout (CRV 65535,
#        reload value 0x6E524635 written at orig 0xE940/0x19DBC), the WDT keeps running across a soft reset, and the
#        SDK takes care of it (nrf_bootloader_wdt_init) only after the DFU decision. Measured without the feed: the WDT
#        reset the chip 2.0 s into the wait, and DFU mode needed a second 2 s wait (~4 s of holding).
src = open(os.path.join(SDK, 'components/libraries/bootloader/nrf_bootloader.c')).read()
src = patch(src, '''/**@brief Function for checking whether to enter DFU mode or not.
 */
static bool dfu_enter_check(void)''', '''/* MOD (Glorious Model O Pro): see tools/mk_bootloader.py. STOCK reads the DFU button once; here it has to stay
 * pressed for DFU_BUTTON_HOLD_MS, because every button of the mouse also wakes it from System OFF (a reset). The wait
 * feeds the watchdog the stock firmware left running (2.0 s timeout), as the stock firmware does. */
static void dfu_wdt_feed(void)
{
    if (NRF_WDT->RUNSTATUS)
    {
        for (uint32_t i = 0; i < 8; i++)
        {
            if (NRF_WDT->RREN & (1UL << i))
            {
                NRF_WDT->RR[i] = 0x6E524635UL;   /* NRF_WDT_RR_VALUE */
            }
        }
    }
}

static bool dfu_button_held(void)
{
    for (uint32_t ms = 0; ms < DFU_BUTTON_HOLD_MS; ms += 10)
    {
        if (nrf_gpio_pin_read(NRF_BL_DFU_ENTER_METHOD_BUTTON_PIN) != 0)
        {
            return false;
        }
        dfu_wdt_feed();
        nrf_delay_ms(10);
    }
    return true;
}

/**@brief Function for checking whether to enter DFU mode or not.
 */
static bool dfu_enter_check(void)''', 'nrf_bootloader.c dfu_enter_check')
src = patch(src, '''    if (NRF_BL_DFU_ENTER_METHOD_BUTTON &&
       (nrf_gpio_pin_read(NRF_BL_DFU_ENTER_METHOD_BUTTON_PIN) == 0))''', '''    if (NRF_BL_DFU_ENTER_METHOD_BUTTON &&
       dfu_button_held())''', 'nrf_bootloader.c button test')
open(os.path.join(OUT, 'nrf_bootloader.c'), 'w').write(src)

# ---- Makefile
ex = os.path.join(EXAMPLE, 'pca10056_s140_ble')
mk = open(os.path.join(ex, 'armgcc/Makefile')).read()
mk = patch(mk, 'OUTPUT_DIRECTORY := _build', 'OUTPUT_DIRECTORY := %s/_build' % OUT, 'output dir')
mk = patch(mk, 'SDK_ROOT := ../../../../..', 'SDK_ROOT := %s' % SDK, 'SDK_ROOT')
mk = patch(mk, 'PROJ_DIR := ../..', 'PROJ_DIR := %s' % EXAMPLE, 'PROJ_DIR')
mk = patch(mk, 'LINKER_SCRIPT  := secure_bootloader_gcc_nrf52.ld',
           'LINKER_SCRIPT  := %s/armgcc/secure_bootloader_gcc_nrf52.ld' % ex, 'linker script')
mk = patch(mk, '$(PROJ_DIR)/../dfu_public_key.c', '%s/dfu_public_key.c' % OUT, 'public key')
mk = patch(mk, '$(PROJ_DIR)/main.c', '%s/main.c' % OUT, 'main.c')
mk = patch(mk, '$(SDK_ROOT)/components/libraries/bootloader/nrf_bootloader.c', '%s/nrf_bootloader.c' % OUT,
           'nrf_bootloader.c')
mk = patch(mk, '  ../config \\', '  %s/config \\\n  %s/fw/bootloader \\' % (ex, ROOT), 'config dir')
# STOCK: BOARD_PCA10056 (devkit pins).  MOD: BOARD_CUSTOM = fw/bootloader/custom_board.h (no LEDs, no devkit buttons).
mk = patch(mk, 'CFLAGS += -DBOARD_PCA10056', 'CFLAGS += -DBOARD_CUSTOM', 'board (C)')
mk = patch(mk, 'ASMFLAGS += -DBOARD_PCA10056', 'ASMFLAGS += -DBOARD_CUSTOM', 'board (asm)')
# STOCK: CONFIG_GPIO_AS_PINRESET makes SystemInit write UICR.PSELRESET when it is not set.
# MOD:   removed, so the bootloader never writes UICR. (This mouse's UICR already selects P0.18 as reset pin.)
mk = patch(mk, 'CFLAGS += -DCONFIG_GPIO_AS_PINRESET\n', '', 'pin reset (C)')
mk = patch(mk, 'ASMFLAGS += -DCONFIG_GPIO_AS_PINRESET\n', '', 'pin reset (asm)')
# sdk_config.h wraps every option in #ifndef, so these -D values replace the example's settings:
overrides = [
    # STOCK example: 32.768 kHz crystal (SRC 1, 20 ppm). MOD: the internal RC oscillator with the values the stock mouse
    # firmware gives the SoftDevice (orig 0x1B154: 00 10 02 01). With a crystal setting and no crystal fitted, the
    # SoftDevice would wait for the clock forever.
    'NRF_SDH_CLOCK_LF_SRC=0', 'NRF_SDH_CLOCK_LF_RC_CTIV=16', 'NRF_SDH_CLOCK_LF_RC_TEMP_CTIV=2',
    'NRF_SDH_CLOCK_LF_ACCURACY=1',
    # STOCK example: devkit button 4 (P0.25). MOD: P1.00, the DPI button (underside), held for 2 s (see above).
    'NRF_BL_DFU_ENTER_METHOD_BUTTON_PIN=32', 'DFU_BUTTON_HOLD_MS=2000',
    # Same value as the example; written out because the bond/config records (0xF6000, 0xF7000) rely on it.
    'NRF_DFU_APP_DATA_AREA_SIZE=12288',
    # STOCK example: "DfuTarg". MOD: a name that says which device is in DFU mode.
    """NRF_DFU_BLE_ADV_NAME='"ModelO DFU"'""",
]
mk = patch(mk, '# C++ flags common to all targets', ''.join('CFLAGS += -D%s\n' % o for o in overrides) +
           '\n# C++ flags common to all targets', 'overrides')
open(os.path.join(OUT, 'Makefile'), 'w').write(mk)

subprocess.check_call(['make', '-C', OUT, '-j8', 'nrf52840_xxaa_s140', 'GNU_INSTALL_ROOT=' + GCC_BIN,
                       'GNU_VERSION=10.3.1'])

# ---- output: the bootloader code only. The SDK linker script also emits UICR records (BOOTLOADERADDR, NRFFW[1]);
# they are dropped here, the install uses the MBR page word 0xFF8/0xFFC instead.
ih = IntelHex(os.path.join(OUT, '_build/nrf52840_xxaa_s140.hex'))
uicr = [a for a in ih.addresses() if a >= 0x10000000]
for a in uicr: del ih[a]
addrs = ih.addresses()
assert BL_START <= min(addrs) and max(addrs) < BL_END, 'bootloader outside 0xF8000-0xFDFFF: %#x-%#x' % (min(addrs), max(addrs))
ih.start_addr = None
ih.write_hex_file(os.path.join(ROOT, 'build/bootloader.hex'))
print('build/bootloader.hex: %#x-%#x (%d of %d bytes used), %d UICR bytes dropped' % (
    min(addrs), max(addrs), max(addrs) + 1 - BL_START, BL_END - BL_START, len(uicr)))
