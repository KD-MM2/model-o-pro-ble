# 04 — Build, step by step

Everything runs from the **repository root** with the virtualenv active
(`source .venv/bin/activate`). `make` is just a wrapper; each step below shows the plain command
so you can see (and change) what happens.

```
stock app ──relocate──> build/golden_app_27000.bin ─┐
blehid.c ──zig cc──> build/blehid.bin ──────────────┼─ mk_ble.py ─> build/s140_730_golden27000_ble.hex
S140 hex (vendor/) ─────────────────────────────────┘
```

## Step 0 — one-time setup

```bash
make venv && source .venv/bin/activate
```

## Step 1 — get the stock app: `stock/golden_app.bin`

From **your** backup ([03](03-backup-restore.md)):

```bash
make stock BACKUP=backups/<date>
# = python tools/extract_stock.py backups/<date>/full_flash_1MB.bin
# initial SP 0x2000af50  reset vector 0x000063dd
# stock/golden_app.bin  sha256 18f8b30ab62fa849206dff5d380259daddd509d96037134a8ba0db9dcad8d165
```

The SHA of the v1.00.00 (2022-08-10, `CM2852_Mouse_USB_v1.00.00_20220810.hex`) app is
`18f8b30a…`. A different hash means a different firmware version; the relocation tables in
`tools/scan.txt` and the hook addresses in `tools/mk_ble.py` are **specific to this binary**
(the patch code asserts the expected bytes at each hook and stops with an `AssertionError`
if they differ). For another version, regenerate the scan (Step 1b) and re-verify every hook.

### Step 1b — (optional) regenerate the relocation scan

```bash
python tools/rebase_scan.py stock/golden_app.bin > /tmp/scan.txt
diff /tmp/scan.txt tools/scan.txt        # only the "image <path>" line differs
```

## Step 2 — get the SoftDevice: `vendor/s140_nrf52_7.3.0_softdevice.hex`

```bash
make softdevice
# 5f460d35…  vendor/s140_nrf52_7.3.0_softdevice.hex
# no UICR records: OK
```

The hex has two segments (MBR 0x0–0xB00, SoftDevice 0x1000–0x26498) and **must not** carry
UICR records (`:020000041000…`); the script refuses if it does. Why 7.3.0: the app's SVC set
fits S140 6.1.1 through 7.3.0 identically (7.x adds only SVCs 0x94–0x96 and 0x13, which the
app never uses), so the newest in hand was taken.

## Step 3 — relocate the app 0x6000 → 0x27000

```bash
python tools/relocate.py 27000 build/golden_app_27000.bin
# patched 584 excluded 210 size 94727 end 0x3e207
```

What it does (details in [07-internals §2](07-internals.md#2-relocation)): adds D = 0x21000 to
every absolute address word that points into the app (vector table, literal pools, data
tables, and the pointers inside the packed RAM-initialisation blob, which it decodes,
patches and re-packs). Output: 94 727 bytes, `sha256 0f583a15…`.

Optional bring-up image (SoftDevice + relocated app, **no BLE**, behaves like the stock
wired mouse):

```bash
python tools/mkhex.py         # -> build/s140_730_golden27000.hex  (0x0 .. 0x3e206)
```

## Step 4 — compile the BLE module

```bash
fw/blehid/build.sh
# ld.lld: warning: cannot find entry symbol _start; not setting start address   <- harmless
# -rwxrwxr-x 1 … 4772 … build/blehid.bin
```

`blehid.c` is freestanding C (no libc, no startup code), linked at **0x40000** with its RAM at
**0x2000B400** (8 KB reserved up to 0x2000D3FF; ~1 KB used). The first 32 bytes are the `ENTRY[8]` table of function pointers
that the assembly stubs use:

| ENTRY | Function | Called by |
|---|---|---|
| 0 | `blehid_init` | boot stub, after `sd_ble_enable` |
| 1 | `blehid_tick` | THUNK, once per main-loop pass |
| 2 | `blehid_send` | (reserved; direct report send) |
| 3 | `&S` | debug: address of the state struct (`0x2000B400`, ~0x3A8 bytes) |
| 4 | `blehid_init_nosd` | boot stub in DONGLE mode (LED + chord only) |
| 5 | `&S.chord_p0` | debug: live chord masks (currently `0x2000B678/7C`; always read the pointer at flash 0x40014) |
| 6 | `blehid_tx_stock` | MOUSE_T, as the BLE leg of the transport |
| 7 | `blehid_before_sleep` | SYSOFF_T, before System OFF |

Useful build knobs (environment variables):

```bash
CFLAGS_EXTRA="-DSTOP_AT=3" fw/blehid/build.sh     # bisect init: stop after stage k, LOG[1]=0x2000|k
ZIG="zig" OBJCOPY=llvm-objcopy fw/blehid/build.sh # use a system zig / objcopy
```

## Step 5 — assemble the final image

```bash
python tools/mk_ble.py 720
# stub 266 thunk 16 blob 4772 attr_tab 720 init 0x400b3 poll 0x40b25 send 0x40ab3 state 0x2000b400
# hex 0x0 0x412a3
sha256sum build/s140_730_golden27000_ble.hex
# d52120ccf9a3a79715ffbc104d89daad8246ebeae59626a8605c12837d812175
```

`720` is the GATT attribute table size passed to `sd_ble_cfg_set` (enough for DIS + BAS +
HID); raising it costs SoftDevice RAM. `mk_ble.py` assembles the stub and thunks with Keystone,
**asserts** the original bytes at every patched site, applies the patches
([07-internals §4](07-internals.md#4-patch-table)), merges SoftDevice + app + stubs + blob into
one Intel-HEX, and writes `build/golden_app_27000_ble.bin` (the patched app alone).

Environment switches: `PUMP=1` (SD event pump flag, normally 0), `NOPOLL=1` (omit the
main-loop hook; used for bisecting).

## Step 6 — verify the build before flashing

```bash
make dry-run              # reads the chip, prints "pages to rewrite: [...]", writes nothing
```

On a chip that already runs this exact image: `pages to rewrite: []`. On a stock chip you
will see MBR/SD pages plus the app region.

You can also disassemble what you built at the hook sites:

```bash
python tools/fdis.py 0x14dc0 0x10          # stock app (orig addresses) – e.g. the transport call site
python tools/fdis.py x 0x15e5c             # who calls the USB transport function
```

(`fdis.py` reads `stock/golden_app.bin`, i.e. **original** 0x6000-based addresses. Add 0x21000
to get the address in the relocated image.)

## Rebuilding after editing `blehid.c`

```bash
make build && make dry-run && make flash
```

Only the changed pages (typically 0x40000–0x41FFF) are rewritten; the SoftDevice, the
relocated app, and your bond are untouched. The mouse resets, reconnects to its bonded host
by itself, and keeps its pairing.
