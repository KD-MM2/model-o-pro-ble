#!/bin/bash
# Build the BLE HID module (fw/blehid/blehid.c) -> build/blehid.bin  (position-dependent blob linked at 0x40000, RAM at 0x2000B400)
set -e
cd "$(dirname "$0")"
mkdir -p ../../build
Z="${ZIG:-python -m ziglang}"                       # pip install ziglang  -> `zig cc` + lld, no ARM toolchain needed
OBJCOPY="${OBJCOPY:-$(command -v llvm-objcopy-21 || command -v llvm-objcopy || echo llvm-objcopy)}"
O=../../build
$Z cc -target thumb-freestanding-eabi -mcpu=cortex_m4 -Os -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -I../sd_api ${CFLAGS_EXTRA} -c blehid.c -o $O/blehid.o -Wall -Wno-unused-function
$Z ld.lld -T link.ld -o $O/blehid.elf $O/blehid.o -Map $O/blehid.map
$OBJCOPY -O binary $O/blehid.elf $O/blehid.bin
ls -la $O/blehid.bin
