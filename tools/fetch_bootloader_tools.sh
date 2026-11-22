#!/bin/bash
# Download and verify what the bootloader build needs, into vendor/ (gitignored):
#   nRF5 SDK 17.1.0          Nordic's secure DFU bootloader sources          vendor/nRF5_SDK_17.1.0_ddde560/
#   Arm GNU Toolchain 10.3   the compiler the SDK makefiles expect            vendor/gcc-arm-none-eabi-10.3-2021.10/
#   nrfutil + nrf5sdk-tools  keys, DFU packages, bootloader settings pages    vendor/bin/nrfutil, vendor/nrfutil-home/
# The sha256 values were taken from the first download (the GCC tarball also matches Arm's published MD5
# 2383e4eb4ea23f248d33adc70dc3227e). A mismatch stops the script.
set -e
cd "$(dirname "$0")/.."
mkdir -p vendor/dl vendor/bin
get() {   # url file sha256
    [ -f "vendor/dl/$2" ] || curl -fL "$1" -o "vendor/dl/$2"
    echo "$3  vendor/dl/$2" | sha256sum -c -
}
get https://nsscprodmedia.blob.core.windows.net/prod/software-and-other-downloads/sdks/nrf5/binaries/nrf5_sdk_17.1.0_ddde560.zip \
    nrf5_sdk_17.1.0_ddde560.zip 5bfe38e744c39fd7f30e10077ba12df306ef91f368894795d6a3e7a62dc68061
get https://developer.arm.com/-/media/Files/downloads/gnu-rm/10.3-2021.10/gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2 \
    gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2 97dbb4f019ad1650b732faffcc881689cedc14e2b7ee863d390e0a41ef16c9a3
get https://files.nordicsemi.com/artifactory/swtools/external/nrfutil/executables/x86_64-unknown-linux-gnu/nrfutil \
    nrfutil a14996288928a92081cadeefd2dd37fcb54ee99a568fd4eaa6fb9586a51fba57
[ -d vendor/nRF5_SDK_17.1.0_ddde560 ] || unzip -q vendor/dl/nrf5_sdk_17.1.0_ddde560.zip -d vendor/
[ -d vendor/gcc-arm-none-eabi-10.3-2021.10 ] || tar -xjf vendor/dl/gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2 -C vendor/
install -m 755 vendor/dl/nrfutil vendor/bin/nrfutil
NRFUTIL_HOME="$PWD/vendor/nrfutil-home" vendor/bin/nrfutil install nrf5sdk-tools
echo "bootloader tools ready"
