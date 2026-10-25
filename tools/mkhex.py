from intelhex import IntelHex
import sys
sd = IntelHex('vendor/s140_nrf52_7.3.0_softdevice.hex')
app = open('build/golden_app_27000.bin','rb').read()
assert sd.maxaddr() < 0x27000 and sd.minaddr() == 0
ih = IntelHex(); ih.merge(sd)
for i, b in enumerate(app): ih[0x27000 + i] = b
assert all(a < 0x10000000 for a in ih.addresses())
ih.write_hex_file('build/s140_730_golden27000.hex')
print(hex(ih.minaddr()), hex(ih.maxaddr()))
