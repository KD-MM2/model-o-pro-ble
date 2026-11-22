// Board definition for the Glorious Model O Pro Wireless, used only by the bootloader (selected with -DBOARD_CUSTOM).
//
// STOCK (Nordic example, BOARD_PCA10056): the devkit's 4 LEDs (P0.13-P0.16) and 4 buttons (P0.11, P0.12, P0.24, P0.25).
// MOD:   none of them. This mouse is wired differently, so the bootloader must not drive any devkit pin. The only pin it
//        uses is the DFU button (NRF_BL_DFU_ENTER_METHOD_BUTTON_PIN, set in tools/mk_bootloader.py: P1.00 = DPI button),
//        read as an input with pull-up, like the stock firmware configures it.
#ifndef CUSTOM_BOARD_H
#define CUSTOM_BOARD_H

#include "nrf_gpio.h"

#define LEDS_NUMBER    0
#define BUTTONS_NUMBER 0
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

#endif
