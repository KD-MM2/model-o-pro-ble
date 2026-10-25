# Run from the repository root.  `make help` lists the targets.
PY      ?= python
$(shell mkdir -p build backups stock vendor)
HEX      = build/s140_730_golden27000_ble.hex
ATTR_TAB ?= 720

help:
	@echo "make venv        create .venv and install the Python tools (once)"
	@echo "make softdevice  download + verify Nordic S140 7.3.0 into vendor/"
	@echo "make backup      read-only 1 MB flash dump into backups/<date>/  (DO THIS FIRST)"
	@echo "make stock       cut stock/golden_app.bin out of BACKUP=<dir>/full_flash_1MB.bin"
	@echo "make build       relocate stock app + build blehid + assemble $(HEX)"
	@echo "make dry-run     compare $(HEX) against the chip, no writes"
	@echo "make flash       write the app region (0x27000..0xFD000)   [normal update]"
	@echo "make flash-first same + MBR/SoftDevice                      [first install only]"
	@echo "make status      non-halting health report of the running mouse"

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

build/blehid.bin: fw/blehid/blehid.c fw/blehid/link.ld
	fw/blehid/build.sh

$(HEX): build/golden_app_27000.bin build/blehid.bin tools/mk_ble.py vendor/s140_nrf52_7.3.0_softdevice.hex
	$(PY) tools/mk_ble.py $(ATTR_TAB)
	sha256sum $(HEX)

build: $(HEX)

dry-run: $(HEX)
	$(PY) tools/nvmc_flash.py $(HEX)

flash: $(HEX)
	$(PY) tools/nvmc_flash.py $(HEX) --go

flash-first: $(HEX)
	$(PY) tools/nvmc_flash.py $(HEX) --go --include-sd

status:
	$(PY) tools/probe.py status

.PHONY: help venv softdevice backup stock build dry-run flash flash-first status
