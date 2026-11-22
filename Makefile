# Run from the repository root.  `make help` lists the targets.
PY      ?= python
$(shell mkdir -p build backups stock vendor)
HEX      = build/s140_730_golden27000_ble.hex
ATTR_TAB ?= 720
DFU_KEY  ?= ../_keys/dfu_private.pem

help:
	@echo "make venv          create .venv and install the Python tools (once)"
	@echo "make softdevice    download + verify Nordic S140 7.3.0 into vendor/"
	@echo "make backup        read-only 1 MB flash dump into backups/<date>/  (DO THIS FIRST)"
	@echo "make stock         cut stock/golden_app.bin out of BACKUP=<dir>/full_flash_1MB.bin"
	@echo "make build         relocate + build the BLE module + assemble $(HEX)"
	@echo "make dry-run       compare the app and settings page with the chip, no writes"
	@echo "make flash         write the app + bootloader settings page over SWD   [update without DFU]"
	@echo "make flash-first   same + MBR/SoftDevice                                [first install only]"
	@echo "make status        non-halting look at the running mouse"
	@echo ""
	@echo "DFU bootloader (BLE updates without SWD):"
	@echo "make bootloader-tools   download + verify nRF5 SDK 17.1.0, Arm GCC 10.3, nrfutil into vendor/ (once)"
	@echo "make dfu-key            create the signing key $(DFU_KEY) (once; BACK IT UP)"
	@echo "make bootloader         build build/bootloader.hex"
	@echo "make dfu                build/app_dfu.zip, the signed update package for the phone app"
	@echo "make bootloader-plan    show what bootloader-install would write (no writes)"
	@echo "make bootloader-install write records, app, settings, bootloader over SWD; MBR not yet told"
	@echo "make bootloader-test    start the installed bootloader in DFU mode (its first run also activates it)"
	@echo "make bootloader-activate  MBR page word 0xFF8 = 0xF8000: the bootloader runs on every reset"
	@echo "make bootloader-deactivate  erase the bootloader's first page: back to MBR -> SoftDevice -> app"

venv:
	python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt
	@echo "now: source .venv/bin/activate"

softdevice:
	tools/fetch_softdevice.sh

backup:
	$(PY) tools/dump_flash.py backups/$$(date +%Y-%m-%d-%H%M)

stock:
	$(PY) tools/extract_stock.py $(BACKUP)/full_flash_1MB.bin

build/golden_app_27000.bin: stock/golden_app.bin tools/relocate.py tools/scan.txt
	$(PY) tools/relocate.py 27000 $@

relocate: build/golden_app_27000.bin

build/blehid.bin: fw/blehid/blehid.c fw/blehid/link.ld
	fw/blehid/build.sh

$(HEX): build/golden_app_27000.bin build/blehid.bin tools/mk_ble.py vendor/s140_nrf52_7.3.0_softdevice.hex
	$(PY) tools/mk_ble.py $(ATTR_TAB)
	sha256sum $(HEX)

build: $(HEX)

# app.hex, settings.hex and app_dfu.zip are made together (same application version)
build/app_dfu.zip: $(HEX) tools/mk_dfu.py $(DFU_KEY)
	$(PY) tools/mk_dfu.py $(DFU_KEY)

dfu: build/app_dfu.zip

dry-run: build/app_dfu.zip
	$(PY) tools/nvmc_flash.py build/app.hex build/settings.hex

flash: build/app_dfu.zip
	$(PY) tools/nvmc_flash.py build/app.hex build/settings.hex --go

flash-first: build/app_dfu.zip
	$(PY) tools/nvmc_flash.py $(HEX) build/settings.hex --go --include-sd

status:
	$(PY) tools/probe.py status

bootloader-tools:
	tools/fetch_bootloader_tools.sh

dfu-key:
	@test ! -e $(DFU_KEY) || { echo "$(DFU_KEY) exists, not overwriting"; exit 1; }
	mkdir -p $(dir $(DFU_KEY)) && chmod 700 $(dir $(DFU_KEY))
	tools/nrfutil keys generate $(DFU_KEY) && chmod 600 $(DFU_KEY)
	@echo "BACK UP $(DFU_KEY): without it the bootloader accepts no update (only SWD can replace it)"

build/bootloader.hex: tools/mk_bootloader.py fw/bootloader/custom_board.h $(DFU_KEY)
	$(PY) tools/mk_bootloader.py $(DFU_KEY)

bootloader: build/bootloader.hex

bootloader-plan: build/bootloader.hex build/app_dfu.zip
	$(PY) tools/install_bootloader.py --activate

bootloader-install: build/bootloader.hex build/app_dfu.zip
	$(PY) tools/install_bootloader.py --go

bootloader-test:
	$(PY) tools/bl_launch.py --dfu

bootloader-activate: build/bootloader.hex build/app_dfu.zip
	$(PY) tools/install_bootloader.py --go --activate

bootloader-deactivate:
	$(PY) tools/install_bootloader.py --go --deactivate

.PHONY: help venv softdevice backup stock relocate build dfu dry-run flash flash-first status bootloader-tools dfu-key \
        bootloader bootloader-plan bootloader-install bootloader-test bootloader-activate bootloader-deactivate
