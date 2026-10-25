import asyncio, sys
from bleak import BleakScanner, BleakClient
async def main():
    name = sys.argv[1] if len(sys.argv) > 1 else 'Model O'
    dev = await BleakScanner.find_device_by_filter(lambda d, ad: name.lower() in (ad.local_name or d.name or '').lower(), timeout=15)
    if not dev:
        print('NOT FOUND'); return
    print('found', dev.address, dev.name)
    async with BleakClient(dev, timeout=20) as c:
        print('connected', c.is_connected)
        try:
            r = await c.pair()
            print('pair result', r)
        except Exception as e:
            print('pair exception', type(e).__name__, e)
        try:
            for s in c.services:
                print('SVC', s.uuid, s.description)
                for ch in s.characteristics:
                    v = ''
                    if 'read' in ch.properties:
                        try: v = (await c.read_gatt_char(ch)).hex()
                        except Exception as e: v = 'ERR ' + type(e).__name__
                    print('   CHR', ch.uuid, ch.properties, v)
        except Exception as e:
            print('services exception', type(e).__name__, e)
asyncio.run(main())
