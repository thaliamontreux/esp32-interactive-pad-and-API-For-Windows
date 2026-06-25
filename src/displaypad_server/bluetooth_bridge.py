"""Bluetooth bridge for DisplayPad devices (multi-pad, Windows-focused).

This script connects to one or more Bluetooth SPP COM ports, speaks a simple
newline-delimited JSON protocol with each DisplayPad, and forwards requests to
an already-running DisplayPad HTTP API server.

Current capabilities:
- Handle initial "hello" message from each pad to learn its pad_uuid.
- Handle "get_config" requests from pads by calling
  GET /api/v1/pads/{pad_uuid}/config on the HTTP API and returning a
  "config" message with the full JSON payload.

Usage (example):

    python -m displaypad_server.bluetooth_bridge \
        --ports COM5 COM6 \
        --api-base http://127.0.0.1:8000

Dependencies (install with pip):

    pip install pyserial requests

This bridge is intentionally decoupled from the FastAPI app runtime; it talks
to the HTTP API just like an external client. This keeps the threading model
simple and makes it easy to run the bridge as a separate process.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, List

import requests
import serial  # type: ignore[import]

from displaypad_server.core.pad_runtime import reconcile_pad_runtime, set_pad_connection, update_pad_status
from displaypad_server.core.timezone_config import get_local_epoch


@dataclass
class PadConnectionState:
    """Represents the state for a single pad over a single COM port."""

    port: str
    serial: serial.Serial
    pad_uuid: Optional[str] = None
    stop_flag: bool = False


class BluetoothBridge:
    """Manages multiple pad connections over Bluetooth SPP (COM ports)."""

    def __init__(self, api_base: str, ports: List[str]) -> None:
        self.api_base = api_base.rstrip("/")
        self.ports = ports
        self._threads: List[threading.Thread] = []
        self._states: Dict[str, PadConnectionState] = {}

    def start(self) -> None:
        """Start worker threads for all configured COM ports."""

        for port in self.ports:
            try:
                ser = serial.Serial(port=port, baudrate=115200, timeout=0.1)
            except Exception as e:  # pragma: no cover - environment-specific
                print(f"[BT-Bridge] Failed to open {port}: {e}", flush=True)
                continue

            state = PadConnectionState(port=port, serial=ser)
            self._states[port] = state

            t = threading.Thread(
                target=self._run_port,
                args=(state,),
                name=f"bt-bridge-{port}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
            print(f"[BT-Bridge] Started worker for {port}", flush=True)

    def stop(self) -> None:
        """Signal all workers to stop and close ports."""

        for state in self._states.values():
            state.stop_flag = True
        for t in self._threads:
            t.join(timeout=1.0)
        for state in self._states.values():
            try:
                state.serial.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Per-port worker
    # ------------------------------------------------------------------

    def _run_port(self, state: PadConnectionState) -> None:
        buf = ""
        port = state.port
        ser = state.serial

        print(f"[BT-Bridge:{port}] Worker running", flush=True)
        while not state.stop_flag:
            try:
                if ser.in_waiting:
                    chunk = ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                    buf += chunk

                    # Process complete lines
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip("\r")
                        if not line:
                            continue
                        self._handle_line(state, line)
                else:
                    time.sleep(0.01)
            except Exception as e:  # pragma: no cover - best-effort logging
                print(f"[BT-Bridge:{port}] Error: {e}", flush=True)
                time.sleep(0.5)

        print(f"[BT-Bridge:{port}] Worker stopping", flush=True)
        if state.pad_uuid:
            set_pad_connection(state.pad_uuid, "bluetooth", False)

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def _handle_line(self, state: PadConnectionState, line: str) -> None:
        port = state.port
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"[BT-Bridge:{port}] Invalid JSON: {e}: {line!r}", flush=True)
            return

        msg_type = msg.get("type")
        pad_uuid = msg.get("pad_uuid") or state.pad_uuid

        if msg_type == "hello":
            if not pad_uuid:
                print(f"[BT-Bridge:{port}] hello missing pad_uuid: {msg}", flush=True)
                return
            state.pad_uuid = str(pad_uuid)
            set_pad_connection(state.pad_uuid, "bluetooth", True)
            fw_version = msg.get("fw_version")
            print(
                f"[BT-Bridge:{port}] Hello from pad {state.pad_uuid[:8]}... "
                f"fw={fw_version}",
                flush=True,
            )
            return

        if not pad_uuid:
            print(f"[BT-Bridge:{port}] Message without pad_uuid: {msg}", flush=True)
            return

        state.pad_uuid = str(pad_uuid)

        if msg_type == "get_config":
            self._handle_get_config(state, msg)
        elif msg_type == "get_time":
            self._handle_get_time(state, msg)
        elif msg_type == "get_host_session_state":
            self._handle_get_host_session_state(state, msg)
        elif msg_type == "pad_status":
            update_pad_status(state.pad_uuid, "bluetooth", msg)
            try:
                import asyncio
                asyncio.run(reconcile_pad_runtime(state.pad_uuid))
            except Exception as e:
                print(f"[BT-Bridge:{port}] Failed to reconcile pad runtime: {e}", flush=True)
        else:
            print(
                f"[BT-Bridge:{port}] Unsupported message type {msg_type!r}: {msg}",
                flush=True,
            )

    # ------------------------------------------------------------------
    # Specific handlers
    # ------------------------------------------------------------------

    def _handle_get_config(self, state: PadConnectionState, msg: dict) -> None:
        """Fetch pad config from HTTP API and send back over Bluetooth.

        Request from pad:
            {"type":"get_config","pad_uuid":"..."}

        Response to pad on success:
            {"type":"config","pad_uuid":"...","config":{...}}
        """

        port = state.port
        pad_uuid = state.pad_uuid
        if not pad_uuid:
            print(f"[BT-Bridge:{port}] get_config without pad_uuid", flush=True)
            return

        url = f"{self.api_base}/api/v1/pads/{pad_uuid}/config"
        try:
            resp = requests.get(url, timeout=5.0)
        except Exception as e:  # pragma: no cover - network/host specific
            print(f"[BT-Bridge:{port}] HTTP error fetching config: {e}", flush=True)
            return

        if resp.status_code != 200:
            print(
                f"[BT-Bridge:{port}] Failed to fetch config for {pad_uuid[:8]}... "
                f"status={resp.status_code}",
                flush=True,
            )
            return

        try:
            config = resp.json()
        except Exception as e:  # pragma: no cover
            print(f"[BT-Bridge:{port}] Invalid JSON in config response: {e}", flush=True)
            return

        reply = {
            "type": "config",
            "pad_uuid": pad_uuid,
            "config": config,
        }
        line = json.dumps(reply, separators=(",", ":"))
        try:
            state.serial.write((line + "\n").encode("utf-8"))
        except Exception as e:  # pragma: no cover
            print(f"[BT-Bridge:{port}] Failed to send config reply: {e}", flush=True)

    def _handle_get_time(self, state: PadConnectionState, msg: dict) -> None:
        port = state.port
        pad_uuid = state.pad_uuid or msg.get("pad_uuid")
        if not pad_uuid:
            print(f"[BT-Bridge:{port}] get_time without pad_uuid", flush=True)
            return

        state.pad_uuid = str(pad_uuid)
        reply = {
            "type": "time",
            "pad_uuid": state.pad_uuid,
            "epoch": get_local_epoch(),
        }
        line = json.dumps(reply, separators=(",", ":"))
        try:
            state.serial.write((line + "\n").encode("utf-8"))
        except Exception as e:  # pragma: no cover
            print(f"[BT-Bridge:{port}] Failed to send time reply: {e}", flush=True)

    def _handle_get_host_session_state(self, state: PadConnectionState, msg: dict) -> None:
        port = state.port
        pad_uuid = state.pad_uuid or msg.get("pad_uuid")
        if not pad_uuid:
            print(f"[BT-Bridge:{port}] get_host_session_state without pad_uuid", flush=True)
            return

        state.pad_uuid = str(pad_uuid)
        url = f"{self.api_base}/api/v1/system/host_session_state"
        try:
            resp = requests.get(url, timeout=5.0)
        except Exception as e:  # pragma: no cover
            print(f"[BT-Bridge:{port}] HTTP error fetching host session state: {e}", flush=True)
            return

        if resp.status_code != 200:
            print(
                f"[BT-Bridge:{port}] Failed to fetch host session state for {state.pad_uuid[:8]}... status={resp.status_code}",
                flush=True,
            )
            return

        try:
            payload = resp.json()
        except Exception as e:  # pragma: no cover
            print(f"[BT-Bridge:{port}] Invalid JSON in host session state response: {e}", flush=True)
            return

        reply = {
            "type": "host_display_state",
            "state": "locked" if bool(payload.get("locked", False)) else "unlocked",
        }
        line = json.dumps(reply, separators=(",", ":"))
        try:
            state.serial.write((line + "\n").encode("utf-8"))
        except Exception as e:  # pragma: no cover
            print(f"[BT-Bridge:{port}] Failed to send host session state reply: {e}", flush=True)


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DisplayPad Bluetooth bridge")
    parser.add_argument(
        "--ports",
        nargs="+",
        required=True,
        help="COM ports to open for Bluetooth SPP (e.g. COM5 COM6)",
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help=(
            "Base URL for DisplayPad HTTP API, "
            "default: http://127.0.0.1:8000"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    bridge = BluetoothBridge(api_base=args.api_base, ports=args.ports)
    bridge.start()

    print(
        f"[BT-Bridge] Running. Bridging ports {args.ports} to {args.api_base}",
        flush=True,
    )

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("[BT-Bridge] Stopping (Ctrl+C)", flush=True)
    finally:
        bridge.stop()


if __name__ == "__main__":  # pragma: no cover
    main()
