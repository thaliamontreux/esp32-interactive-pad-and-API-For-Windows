"""UDP Discovery service for DisplayPad devices.

Listens for beacon broadcasts from ESP32 devices and tracks discovered pads.
"""

import socket
import struct
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

# Discovery constants
DISCOVERY_BROADCAST_PORT = 7444
DISCOVERY_ASSIGN_PORT = 7445
BEACON_MAGIC = b"DSPPAD"
BEACON_VERSION = 1

# Beacon packet structure
BEACON_FORMAT = "<6s B B 32s 18s H H B H B"  # magic, version, type, uuid, mac, width, height, buttons, port, flags
ASSIGN_FORMAT = "<6s B B 32s 64s 32s H"  # magic, version, type, uuid, token, api_uuid, port


class DiscoveredPad:
    """Represents a discovered but not yet assigned pad."""

    def __init__(self, uuid: str, mac: str, ip: str, width: int, height: int, buttons: int):
        self.uuid = uuid
        self.mac = mac
        self.ip = ip
        self.screen_width = width
        self.screen_height = height
        self.button_count = buttons
        self.discovered_at = datetime.now(timezone.utc)
        self.last_seen = datetime.now(timezone.utc)
        self.assigned = False

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "mac": self.mac,
            "ip": self.ip,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "button_count": self.button_count,
            "discovered_at": self.discovered_at.isoformat(),
            "last_seen": self.last_seen.isoformat(),
        }


class DiscoveryService:
    """UDP discovery service that listens for ESP32 beacons."""

    def __init__(self):
        self._discovered: Dict[str, DiscoveredPad] = {}
        self._lock = threading.Lock()
        self._running = False
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._on_discovered: Optional[Callable[[DiscoveredPad], None]] = None

    def start(self, on_discovered: Optional[Callable[[DiscoveredPad], None]] = None):
        """Start the discovery service."""
        self._on_discovered = on_discovered
        self._running = True

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("0.0.0.0", DISCOVERY_BROADCAST_PORT))
        self._socket.settimeout(1.0)  # 1 second timeout for clean shutdown

        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

        print(f"[Discovery] Service started on port {DISCOVERY_BROADCAST_PORT}")

    def stop(self):
        """Stop the discovery service."""
        self._running = False
        if self._socket:
            self._socket.close()
        if self._thread:
            self._thread.join(timeout=2)
        print("[Discovery] Service stopped")

    def _listen_loop(self):
        """Main listening loop."""
        while self._running:
            try:
                data, addr = self._socket.recvfrom(1024)
                self._process_packet(data, addr[0])
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    print(f"[Discovery] Error: {e}")

    def _process_packet(self, data: bytes, ip: str):
        """Process a received beacon packet."""
        if len(data) < 6:
            return

        # Check magic
        magic = data[:6]
        if magic != BEACON_MAGIC:
            return

        # Parse beacon
        try:
            unpacked = struct.unpack(BEACON_FORMAT, data[:struct.calcsize(BEACON_FORMAT)])
            _, version, packet_type, uuid_bytes, mac_bytes, width, height, buttons, port, flags = unpacked

            if version != BEACON_VERSION:
                return
            if packet_type != 1:  # BEACON
                return

            uuid = uuid_bytes.decode("utf-8").rstrip("\x00")
            mac = mac_bytes.decode("utf-8").rstrip("\x00")

            # Skip if already assigned
            if flags & 0x01:
                return

            with self._lock:
                now = datetime.now(timezone.utc)

                if uuid in self._discovered:
                    # Update existing
                    self._discovered[uuid].last_seen = now
                    self._discovered[uuid].ip = ip  # IP might change
                else:
                    # New discovery
                    pad = DiscoveredPad(
                        uuid=uuid,
                        mac=mac,
                        ip=ip,
                        width=width,
                        height=height,
                        buttons=buttons,
                    )
                    self._discovered[uuid] = pad
                    print(f"[Discovery] New pad discovered: {uuid[:16]}... at {ip}")

                    if self._on_discovered:
                        self._on_discovered(pad)

        except struct.error:
            pass  # Invalid packet format
        except Exception as e:
            print(f"[Discovery] Parse error: {e}")

    def get_discovered(self) -> list:
        """Get list of discovered (unassigned) pads."""
        with self._lock:
            # Remove old entries (>5 minutes)
            now = datetime.now(timezone.utc)
            cutoff = now.timestamp() - 300
            expired = [uuid for uuid, pad in self._discovered.items()
                      if pad.last_seen.timestamp() < cutoff]
            for uuid in expired:
                del self._discovered[uuid]

            return [pad.to_dict() for pad in self._discovered.values() if not pad.assigned]

    def add_discovered_pad(self, uuid: str, mac: str, ip: str, width: int, height: int, buttons: int):
        """Add a pad that contacted us via HTTP hello (active scanning mode)."""
        with self._lock:
            now = datetime.now(timezone.utc)

            if uuid in self._discovered:
                # Update existing
                self._discovered[uuid].last_seen = now
                self._discovered[uuid].ip = ip
                print(f"[Discovery] Updated pad {uuid[:16]}... at {ip}")
            else:
                # New discovery
                pad = DiscoveredPad(
                    uuid=uuid,
                    mac=mac,
                    ip=ip,
                    width=width,
                    height=height,
                    buttons=buttons,
                )
                self._discovered[uuid] = pad
                print(f"[Discovery] New pad via hello: {uuid[:16]}... at {ip}")

                if self._on_discovered:
                    self._on_discovered(pad)

    def assign_pad(self, uuid: str, device_token: str, api_uuid: str, api_port: int) -> bool:
        """Send assignment packet to a discovered pad."""
        with self._lock:
            if uuid not in self._discovered:
                print(f"[Discovery] Cannot assign: {uuid[:16]}... not found")
                return False

            pad = self._discovered[uuid]
            pad.assigned = True

        # Build assignment packet
        uuid_bytes = uuid.encode("utf-8")[:32].ljust(32, b"\x00")
        token_bytes = device_token.encode("utf-8")[:64].ljust(64, b"\x00")
        api_uuid_bytes = api_uuid.encode("utf-8")[:32].ljust(32, b"\x00")

        packet = struct.pack(
            ASSIGN_FORMAT,
            BEACON_MAGIC,
            BEACON_VERSION,
            2,  # ASSIGN type
            uuid_bytes,
            token_bytes,
            api_uuid_bytes,
            api_port,
        )

        # Send to pad
        return self._send_assign_packet(packet, pad.ip)

    def assign_pad_to_ip(self, uuid: str, ip: str, device_token: str, api_uuid: str, api_port: int) -> bool:
        """Send assignment packet directly to a specific IP.

        Used on server startup to re-send ASSIGN to pads whose IP we
        remembered from the database, without requiring them to be in
        the in-memory discovered list yet.
        """

        uuid_bytes = uuid.encode("utf-8")[:32].ljust(32, b"\x00")
        token_bytes = device_token.encode("utf-8")[:64].ljust(64, b"\x00")
        api_uuid_bytes = api_uuid.encode("utf-8")[:32].ljust(32, b"\x00")

        packet = struct.pack(
            ASSIGN_FORMAT,
            BEACON_MAGIC,
            BEACON_VERSION,
            2,  # ASSIGN type
            uuid_bytes,
            token_bytes,
            api_uuid_bytes,
            api_port,
        )

        return self._send_assign_packet(packet, ip)

    def _send_assign_packet(self, packet: bytes, ip: str) -> bool:
        """Low-level helper to send an ASSIGN packet to a target IP."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(packet, (ip, DISCOVERY_ASSIGN_PORT))
            sock.close()
            print(f"[Discovery] Assignment sent to {ip}")
            return True
        except Exception as e:
            print(f"[Discovery] Failed to send assignment: {e}")
            return False


# Global instance
discovery_service = DiscoveryService()
