# Run from the repository root.  `make help` lists the targets.
PY      ?= python
$(shell mkdir -p build backups stock vendor)

help:
	@echo "make venv        create .venv and install the Python tools (once)"
	@echo "make softdevice  download + verify Nordic S140 7.3.0 into vendor/"
	@echo "make backup      read-only 1 MB flash dump into backups/<date>/  (DO THIS FIRST)"
	@echo "make stock       cut stock/golden_app.bin out of BACKUP=<dir>/full_flash_1MB.bin"
	@echo "make relocate    move the stock app from 0x6000 to 0x27000 (room for the SoftDevice)"
	@echo "make status      non-halting look at the running mouse"

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

status:
	$(PY) tools/probe.py status

.PHONY: help venv softdevice backup stock relocate status
