import asyncio

from bleak import BleakScanner, BleakClient


TARGET_PREFIX = "PAD-"


async def main() -> None:
    print("[BLE-Test] Scanning for DisplayPad devices...")
    devices = await BleakScanner.discover(timeout=5.0)

    pads = [d for d in devices if d.name and d.name.startswith(TARGET_PREFIX)]
    if not pads:
        print("[BLE-Test] No PAD-xxxx devices found. Make sure the pad's Bluetooth pairing screen is open.")
        return

    for idx, d in enumerate(pads):
        print(f"[{idx}] {d.name} ({d.address})")

    target = pads[0]
    print(f"[BLE-Test] Connecting to {target.name} at {target.address}...")

    async with BleakClient(target) as client:
        print(f"[BLE-Test] Connected: {client.is_connected}")

        print("[BLE-Test] Services:")
        for service in client.services:
            print(f"  Service {service.uuid}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"    Char {char.uuid} props=[{props}]")


if __name__ == "__main__":
    asyncio.run(main())
