import asyncio, sys
from bleak import BleakClient
import os
ADDR = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('MOUSE_ADDR', 'AA:BB:CC:DD:EE:FF')   # the mouse's BLE address (see ble_scan.py)
async def main():
    c = BleakClient(ADDR, timeout=15)
    try:
        await c.connect()
    except Exception as e:
        print('connect exception', type(e).__name__, e)
    try:
        print('unpair', await c.unpair())
    except Exception as e:
        print('unpair exception', type(e).__name__, e)
    try: await c.disconnect()
    except Exception: pass
asyncio.run(main())
