import asyncio, sys
from bleak import BleakScanner
async def main():
    match = sys.argv[1] if len(sys.argv) > 1 else 'Model O'
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 10
    found = {}
    def cb(d, ad):
        found[d.address] = (d, ad)
    async with BleakScanner(cb, scanning_mode='active'):
        await asyncio.sleep(secs)
    n = 0
    for a, (d, ad) in found.items():
        name = ad.local_name or d.name or ''
        if match == '*' or match.lower() in name.lower():
            n += 1
            print(a, repr(name), 'rssi', ad.rssi, 'uuids', ad.service_uuids, 'appearance?', ad.manufacturer_data, ad.platform_data[1].__class__.__name__ if ad.platform_data else '')
    print('seen', len(found), 'matched', n)
asyncio.run(main())
