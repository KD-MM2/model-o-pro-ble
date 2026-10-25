import asyncio, sys
from bleak import BleakClient
import os
ADDR = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('MOUSE_ADDR', 'AA:BB:CC:DD:EE:FF')   # the mouse's BLE address (see ble_scan.py)
async def main():
    c = BleakClient(ADDR, timeout=15)
    try:
        await c.connect()
        v = await c.read_gatt_char('00002a19-0000-1000-8000-00805f9b34fb')
        print('battery level over BLE (BAS 0x2A19):', v[0], '%')
    except Exception as e:
        print('exception', type(e).__name__, e)
    try: await c.disconnect()
    except Exception: pass
asyncio.run(main())
