#!/usr/bin/env python3
"""extract_stock.py <full_flash_1MB.bin> -- cut the stock vendor application out of a flash dump into stock/golden_app.bin.
The stock app lives at 0x6000..0x1CC8F (93 328 bytes) on a mouse that runs the stock firmware."""
import sys, hashlib
d = open(sys.argv[1], 'rb').read()
app = d[0x6000:0x1CC90]
assert len(d) >= 0x1CC90 and len(app) == 93328
sp, rv = int.from_bytes(app[0:4], 'little'), int.from_bytes(app[4:8], 'little')
print('initial SP 0x%08x  reset vector 0x%08x' % (sp, rv))
assert sp >> 20 == 0x200 and 0x6000 <= rv < 0x1CC90 and rv & 1, 'does not look like the stock app at 0x6000 (wrong dump?)'
open('stock/golden_app.bin', 'wb').write(app)
print('stock/golden_app.bin  sha256', hashlib.sha256(app).hexdigest())
print('expected for Model O Pro Wireless CM2852_Mouse_USB_v1.00.00_20220810: 18f8b30a...')
