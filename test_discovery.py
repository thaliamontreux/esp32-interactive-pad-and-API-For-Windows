"""Test script to verify UDP discovery is working."""
import socket
import struct
import time

BEACON_MAGIC = b"DSPPAD"
BEACON_FORMAT = "<6s B B 32s 18s H H B H B"

def listen_for_beacons(duration=30):
    """Listen for ESP32 beacons."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', 7444))
    sock.settimeout(1.0)

    print(f"Listening for beacons on port 7444 for {duration} seconds...")
    print("Make sure ESP32 is powered on and in discovery mode (showing 'Waiting for Server')")
    print()

    found = []
    start = time.time()

    while time.time() - start < duration:
        try:
            data, addr = sock.recvfrom(1024)
            if len(data) < struct.calcsize(BEACON_FORMAT):
                continue

            unpacked = struct.unpack(BEACON_FORMAT, data[:struct.calcsize(BEACON_FORMAT)])
            magic, version, pkt_type, uuid_bytes, mac_bytes, width, height, buttons, port, flags = unpacked

            if magic != BEACON_MAGIC or version != 1:
                continue

            uuid = uuid_bytes.decode('utf-8').rstrip('\x00')
            mac = mac_bytes.decode('utf-8').rstrip('\x00')

            if uuid not in [f[0] for f in found]:
                found.append((uuid, addr[0], mac, width, height))
                print(f"✓ Found pad: {uuid[:16]}...")
                print(f"  IP: {addr[0]}")
                print(f"  MAC: {mac}")
                print(f"  Screen: {width}x{height}, Buttons: {buttons}")
                print()

        except socket.timeout:
            continue
        except Exception as e:
            print(f"Error: {e}")

    sock.close()

    if not found:
        print("\n❌ No beacons received!")
        print("\nTroubleshooting:")
        print("1. ESP32 may have existing pairing data")
        print("2. Check firewall - UDP port 7444 must be open")
        print("3. ESP32 and PC must be on same network/subnet")
        print("\nTo fix: Upload firmware with 'Erase Flash' option or:")
        print("  - Open control panel on ESP32 (hold corner buttons)")
        print("  - Select 'Reset Pairing Only'")
        print("  - Reboot ESP32")
    else:
        print(f"\n✓ Found {len(found)} pad(s) total")

    return found


if __name__ == "__main__":
    pads = listen_for_beacons(30)
