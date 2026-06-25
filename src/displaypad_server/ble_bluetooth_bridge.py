"""BLE GATT bridge for DisplayPad devices using Bleak.

This script connects to one DisplayPad over BLE (custom GATT JSON service)
and forwards its requests to an already-running DisplayPad HTTP API server.

It mirrors the behavior of bluetooth_bridge.py, but instead of talking to a
serial COM port (SPP), it talks directly to the ESP32's BLE GATT service.

Usage (example):

    python -m displaypad_server.ble_bluetooth_bridge \
        --api-base http://127.0.0.1:7443

On startup it will:
- Scan for devices whose name starts with "PAD-".
- Connect to the first one found.
- Subscribe to notifications on the TX characteristic.
- Handle:
    - "hello" messages to learn pad_uuid.
    - "get_config" messages by calling
      GET /api/v1/pads/{pad_uuid}/config on the HTTP API and sending
      back a "config" message with the payload.

Dependencies:

    pip install bleak requests

"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
import time as _time
from typing import Optional, Dict, List, Set

import requests
from bleak import BleakClient, BleakScanner

from displaypad_server.core import logging as dp_logging
from displaypad_server.core.pad_runtime import reconcile_pad_runtime, set_pad_connection, update_pad_status
from displaypad_server.core.timezone_config import get_local_epoch, get_timezone_config


# Must match the ESP32 firmware (bluetooth_manager.cpp)
SERVICE_UUID = "12345678-1234-1234-1234-1234567890ab"
TX_CHAR_UUID = "12345678-1234-1234-1234-1234567890ac"  # pad -> host (notify)
RX_CHAR_UUID = "12345678-1234-1234-1234-1234567890ad"  # host -> pad (write)

DEVICE_NAME_PREFIX = "PAD-"
BLE_MAX_CHUNK = 20
BLE_WRITE_ATTEMPTS = 3


def _ts() -> str:
    """Return a short wall-clock timestamp for log messages."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


@dataclass
class PadBleState:
    api_base: str
    client: BleakClient
    tx_char_uuid: str
    rx_char_uuid: str
    pad_uuid: Optional[str] = None
    rx_buffer: str = ""
    # True while we are in the middle of sending a large multi-chunk
    # configuration reply. While this is set, we avoid sending auxiliary
    # messages such as time updates so that their JSON does not get
    # interleaved with the config payload on the device side.
    sending_config: bool = False
    write_lock: Optional[asyncio.Lock] = None
    pending_time_sync: bool = False


# Registry of active BLE connections keyed by pad UUID so that other parts of
# the server (e.g. the Task Keypad monitor) can push JSON messages such as
# task_app_state updates to Bluetooth-connected pads.
_connected_ble_pads: Dict[str, PadBleState] = {}
_task_state_snapshot_requests: Set[str] = set()


def request_task_app_state_snapshot(pad_uuid: str) -> None:
    if pad_uuid:
        _task_state_snapshot_requests.add(str(pad_uuid))


def consume_task_app_state_snapshot_request(pad_uuid: str) -> bool:
    if pad_uuid in _task_state_snapshot_requests:
        _task_state_snapshot_requests.discard(pad_uuid)
        return True
    return False


async def _write_ble_bytes(state: PadBleState, data: bytes) -> bool:
    try:
        if not state.client.is_connected:
            return False
    except Exception:
        return False

    total_len = len(data)
    lock = state.write_lock
    if lock is None:
        lock = asyncio.Lock()
        state.write_lock = lock

    last_error: Exception | None = None
    for attempt in range(1, BLE_WRITE_ATTEMPTS + 1):
        try:
            async with lock:
                offset = 0
                while offset < total_len:
                    chunk = data[offset : offset + BLE_MAX_CHUNK]
                    await state.client.write_gatt_char(
                        state.rx_char_uuid,
                        chunk,
                        response=True,
                    )
                    offset += len(chunk)
            return True
        except Exception as e:
            last_error = e
            if attempt >= BLE_WRITE_ATTEMPTS:
                break
            await asyncio.sleep(0.15 * attempt)

    if last_error is not None:
        raise last_error
    return False


async def _write_ble_json(state: PadBleState, payload: dict) -> bool:
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    return await _write_ble_bytes(state, line.encode("utf-8"))


async def _handle_line(state: PadBleState, line: str) -> None:
    """Handle a single JSON line received from the pad over BLE."""
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        print(f"[{_ts()}] [BLE-Bridge] Invalid JSON from pad: {e}: {line!r}", flush=True)
        return

    msg_type = msg.get("type")
    pad_uuid = msg.get("pad_uuid") or state.pad_uuid

    if msg_type == "hello":
        if not pad_uuid:
            print(f"[{_ts()}] [BLE-Bridge] hello missing pad_uuid: {msg}", flush=True)
            return
        state.pad_uuid = str(pad_uuid)
        _connected_ble_pads[state.pad_uuid] = state
        set_pad_connection(state.pad_uuid, "ble", True)
        fw_version = msg.get("fw_version")
        short_id = state.pad_uuid[:8]
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] Hello from pad {short_id}... fw={fw_version}",
        )

        # Immediately send a time sync message so the pad can mirror the
        # host's current clock without any additional timezone math on the
        # device. We encode the local wall-clock time as an epoch and do not
        # send a separate timezone offset.
        await _send_time_update(state)
        return

    if not pad_uuid:
        print(f"[{_ts()}] [BLE-Bridge] Message without pad_uuid: {msg}", flush=True)
        return

    state.pad_uuid = str(pad_uuid)
    _connected_ble_pads[state.pad_uuid] = state

    if msg_type == "get_config":
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] Received get_config from pad {state.pad_uuid}",
        )
        await _handle_get_config(state, msg)
    elif msg_type == "get_time":
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] Received get_time from pad {state.pad_uuid}",
        )
        await _handle_get_time(state, msg)
    elif msg_type == "get_host_session_state":
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] Received get_host_session_state from pad {state.pad_uuid}",
        )
        await _handle_get_host_session_state(state, msg)
    elif msg_type == "pad_status":
        update_pad_status(state.pad_uuid, "ble", msg)
        await reconcile_pad_runtime(state.pad_uuid)
    elif msg_type == "button_press":
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] Received button_press from pad {state.pad_uuid}: {msg}",
        )
        await _handle_button_press(state, msg)
    elif msg_type == "task_app_state_ack":
        version = msg.get("version")
        active = msg.get("active_slots") or []
        short_id = state.pad_uuid[:8] if state.pad_uuid else "????????"
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] Ack from pad {short_id} for task_app_state "
            f"version={version} active_slots={active}",
        )
    else:
        print(f"[{_ts()}] [BLE-Bridge] Unsupported message type {msg_type!r}: {msg}", flush=True)


async def _handle_get_config(state: PadBleState, msg: dict) -> None:
    """Fetch pad config from HTTP API and send back over BLE.

    Request from pad:
        {"type":"get_config","pad_uuid":"..."}

    Response to pad on success:
        {"type":"config","pad_uuid":"...","config":{...}}
    """

    # Prefer the pad_uuid we already learned from an earlier hello, but fall
    # back to the value provided in this message so that the very first
    # get_config can succeed even if it races ahead of hello.
    pad_uuid = state.pad_uuid or msg.get("pad_uuid")
    if not pad_uuid:
        print(f"[{_ts()}] [BLE-Bridge] get_config without pad_uuid", flush=True)
        return

    # Persist the pad_uuid once we know it so subsequent messages do not need
    # to resend it.
    state.pad_uuid = str(pad_uuid)
    state.sending_config = True

    url = f"{state.api_base}/api/v1/pads/{pad_uuid}/config"
    print(f"[{_ts()}] [BLE-Bridge] Fetching config for {pad_uuid} from {url}", flush=True)

    start_http = _time.time()
    try:
        # Allow a reasonable timeout for the pad config endpoint since it may
        # touch the database and icon metadata, but fail fast if the API is
        # unavailable so the pad can retry instead of waiting a full minute.
        #
        # IMPORTANT: run the blocking requests.get call in a worker thread via
        # asyncio.to_thread so we do not block the FastAPI/uvicorn event loop
        # when the bridge is embedded inside the API process.
        resp = await asyncio.to_thread(requests.get, url, timeout=15.0)
    except Exception as e:
        print(f"[{_ts()}] [BLE-Bridge] HTTP error fetching config after {(_time.time()-start_http):.3f}s: {e}", flush=True)
        state.sending_config = False
        return

    if resp.status_code != 200:
        print(
            f"[{_ts()}] [BLE-Bridge] Failed to fetch config for {pad_uuid[:8]}... "
            f"status={resp.status_code} in {(_time.time()-start_http):.3f}s",
            flush=True,
        )
        state.sending_config = False
        return

    try:
        config = resp.json()
    except Exception as e:
        print(f"[{_ts()}] [BLE-Bridge] Invalid JSON in config response: {e}", flush=True)
        state.sending_config = False
        return

    reply = {
        "type": "config",
        "pad_uuid": pad_uuid,
        "config": config,
    }
    data = (json.dumps(reply, separators=(",", ":")) + "\n").encode("utf-8")
    total_len = len(data)
    chunks = (len(data) + BLE_MAX_CHUNK - 1) // BLE_MAX_CHUNK

    dp_logging.log_debug(
        "ble_bridge",
        f"[{_ts()}] [BLE-Bridge] Sending config reply over BLE: {total_len} bytes in {chunks} chunks",
    )

    # Mark that we are in the middle of a large reply so that other
    # background tasks (such as periodic time sync) do not interleave their
    # JSON messages into the same line buffer on the device.
    try:
        await _write_ble_bytes(state, data)

        dp_logging.log_debug("ble_bridge", f"[{_ts()}] [BLE-Bridge] Sent config reply to pad")
        request_task_app_state_snapshot(str(pad_uuid))
    except Exception as e:
        print(f"[{_ts()}] [BLE-Bridge] Failed to send config reply: {e}", flush=True)
    finally:
        state.sending_config = False

    # Immediately follow the config reply with a time update so that the pad
    # receives a {"type":"time"} message while loadConfigFromBLE is still
    # running. This ensures the ESP32 sets its RTC from the host clock during
    # the same session it applies the config.
    await _send_time_update(state)


async def _handle_get_time(state: PadBleState, msg: dict) -> None:
    pad_uuid = state.pad_uuid or msg.get("pad_uuid")
    if not pad_uuid:
        print(f"[{_ts()}] [BLE-Bridge] get_time without pad_uuid", flush=True)
        return

    state.pad_uuid = str(pad_uuid)
    if state.sending_config:
        state.pending_time_sync = True
        return
    await _send_time_update(state)


async def _handle_get_host_session_state(state: PadBleState, msg: dict) -> None:
    pad_uuid = state.pad_uuid or msg.get("pad_uuid")
    if not pad_uuid:
        print(f"[{_ts()}] [BLE-Bridge] get_host_session_state without pad_uuid", flush=True)
        return

    state.pad_uuid = str(pad_uuid)
    if state.sending_config:
        return

    url = f"{state.api_base}/api/v1/system/host_session_state"
    try:
        resp = await asyncio.to_thread(requests.get, url, timeout=5.0)
    except Exception as e:
        print(f"[{_ts()}] [BLE-Bridge] HTTP error fetching host session state: {e}", flush=True)
        return

    if resp.status_code != 200:
        print(
            f"[{_ts()}] [BLE-Bridge] Failed to fetch host session state for {state.pad_uuid[:8]}... status={resp.status_code}",
            flush=True,
        )
        return

    try:
        payload = resp.json()
    except Exception as e:
        print(f"[{_ts()}] [BLE-Bridge] Invalid JSON in host session state response: {e}", flush=True)
        return

    locked = bool(payload.get("locked", False))
    await _write_ble_json(
        state,
        {"type": "host_display_state", "state": "locked" if locked else "unlocked"},
    )


async def _send_time_update(state: PadBleState) -> bool:
    """Send a time update to the pad using the host's local wall-clock time.

    We intentionally avoid exposing timezone/DST details to the device. The
    epoch we send is derived from the local time so that, when the ESP32
    renders it without any offset adjustments, its clock matches the host.
    """

    if not state.pad_uuid:
        return False

    # If we are in the middle of streaming a large config reply, skip time
    # updates for now. They will be sent again on the next periodic tick.
    if state.sending_config:
        state.pending_time_sync = True
        return False

    try:
        # Use the host's current local epoch based on the configured timezone
        # (default CDT). The ESP32 treats this epoch as a wall-clock value,
        # so no additional timezone math is required on the device.
        epoch_local = get_local_epoch()

        time_msg = {
            "type": "time",
            "pad_uuid": state.pad_uuid,
            "epoch": epoch_local,
        }
        ok = await _write_ble_json(state, time_msg)
        if not ok:
            return False
        state.pending_time_sync = False
        tz_cfg = get_timezone_config()
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] Sent time update to pad epoch={epoch_local} tz={tz_cfg.timezone_name}",
        )
        return True
    except Exception as e:
        print(f"[{_ts()}] [BLE-Bridge] Failed to send time update: {e}", flush=True)
        return False


async def _handle_button_press(state: PadBleState, msg: dict) -> None:
    """Forward a button press event from the pad to the HTTP API.

    Request from pad:
        {"type":"button_press","pad_uuid":"...","slot":N,"press_type":"tap"}
    """

    pad_uuid = state.pad_uuid or msg.get("pad_uuid")
    if not pad_uuid:
        print(f"[{_ts()}] [BLE-Bridge] button_press without pad_uuid: {msg}", flush=True)
        return

    slot = msg.get("slot")
    press_type = msg.get("press_type", "tap")
    if slot is None:
        print(f"[{_ts()}] [BLE-Bridge] button_press missing slot: {msg}", flush=True)
        return

    url = f"{state.api_base}/api/v1/pads/{pad_uuid}/press"
    payload = {"slot": slot, "press_type": press_type}

    start_http = _time.time()
    try:
        resp = await asyncio.to_thread(requests.post, url, json=payload, timeout=15.0)
    except Exception as e:
        print(f"[{_ts()}] [BLE-Bridge] HTTP error forwarding button_press after {(_time.time()-start_http):.3f}s: {e}", flush=True)
        return

    if resp.status_code != 200:
        print(
            f"[{_ts()}] [BLE-Bridge] Failed to forward button_press for {pad_uuid[:8]}... "
            f"status={resp.status_code} in {(_time.time()-start_http):.3f}s",
            flush=True,
        )


def _notification_handler(state: PadBleState, loop: asyncio.AbstractEventLoop):
    """Create a Bleak notification callback that buffers and dispatches lines."""

    def _cb(_sender: int, data: bytearray) -> None:
        text = data.decode("utf-8", errors="ignore")
        state.rx_buffer += text

        decoder = json.JSONDecoder()
        message_start_token = '{"type"'
        while True:
            buffer = state.rx_buffer.lstrip("\r\n\t ")
            trimmed = len(state.rx_buffer) - len(buffer)
            if trimmed:
                state.rx_buffer = buffer

            if not state.rx_buffer:
                break

            start = state.rx_buffer.find("{")
            if start < 0:
                state.rx_buffer = ""
                break
            if start > 0:
                state.rx_buffer = state.rx_buffer[start:]

            try:
                obj, end = decoder.raw_decode(state.rx_buffer)
            except json.JSONDecodeError as exc:
                next_start = state.rx_buffer.find(message_start_token, 1)
                if next_start > 0:
                    state.rx_buffer = state.rx_buffer[next_start:]
                    continue

                if exc.pos > 0:
                    candidate = state.rx_buffer.find("{", exc.pos)
                    if candidate > 0:
                        state.rx_buffer = state.rx_buffer[candidate:]
                        continue

                if "\n" in state.rx_buffer:
                    _, state.rx_buffer = state.rx_buffer.split("\n", 1)
                    continue
                break

            line = json.dumps(obj, separators=(",", ":"))
            state.rx_buffer = state.rx_buffer[end:]
            loop.call_soon_threadsafe(asyncio.create_task, _handle_line(state, line))

    return _cb


async def run_bridge(api_base: str, device_name: Optional[str]) -> None:
    api_base = api_base.rstrip("/")
    dp_logging.log_debug(
        "ble_bridge",
        f"[{_ts()}] [BLE-Bridge] Using API base: {api_base}",
    )

    # Discover target device
    dp_logging.log_debug(
        "ble_bridge",
        f"[{_ts()}] [BLE-Bridge] Scanning for DisplayPad devices...",
    )
    devices = await BleakScanner.discover(timeout=5.0)

    pads = [d for d in devices if d.name and d.name.startswith(DEVICE_NAME_PREFIX)]
    if device_name:
        pads = [d for d in pads if d.name == device_name]

    if not pads:
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] No PAD-xxxx devices found. "
            "Make sure the pad's Bluetooth pairing screen is open.",
        )
        return

    dp_logging.log_debug("ble_bridge", f"[{_ts()}] [BLE-Bridge] Found pads:")
    for idx, d in enumerate(pads):
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}]   [{idx}] {d.name} ({d.address})",
        )

    target = pads[0]
    dp_logging.log_debug(
        "ble_bridge",
        f"[{_ts()}] [BLE-Bridge] Connecting to {target.name} at {target.address}...",
    )

    async with BleakClient(target) as client:
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] Connected: {client.is_connected}",
        )

        # Verify that our custom service/characteristics exist.
        service = client.services.get_service(SERVICE_UUID)
        if service is None:
            print(
                f"[{_ts()}] [BLE-Bridge] Service {SERVICE_UUID} not found on device; "
                "is this a DisplayPad firmware?",
                flush=True,
            )
            return

        if service.get_characteristic(TX_CHAR_UUID) is None:
            print(
                f"[{_ts()}] [BLE-Bridge] TX characteristic {TX_CHAR_UUID} not found on device",
                flush=True,
            )
            return

        if service.get_characteristic(RX_CHAR_UUID) is None:
            print(
                f"[{_ts()}] [BLE-Bridge] RX characteristic {RX_CHAR_UUID} not found on device",
                flush=True,
            )
            return

        state = PadBleState(
            api_base=api_base,
            client=client,
            tx_char_uuid=TX_CHAR_UUID,
            rx_char_uuid=RX_CHAR_UUID,
            write_lock=asyncio.Lock(),
        )

        loop = asyncio.get_running_loop()
        await client.start_notify(TX_CHAR_UUID, _notification_handler(state, loop))
        dp_logging.log_debug(
            "ble_bridge",
            f"[{_ts()}] [BLE-Bridge] Subscribed to TX notifications; waiting for messages...",
        )

        last_time_sync = 0.0

        try:
            # Run until disconnected or Ctrl+C
            while True:
                if not client.is_connected:
                    dp_logging.log_debug(
                        "ble_bridge",
                        f"[{_ts()}] [BLE-Bridge] Client disconnected",
                    )
                    break

                # Periodic time sync: update the pad's clock every 2 minutes
                now = _time.time()
                if state.pad_uuid and state.pending_time_sync:
                    if await _send_time_update(state):
                        last_time_sync = now
                elif state.pad_uuid and now - last_time_sync >= 120.0:
                    if await _send_time_update(state):
                        last_time_sync = now

                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            dp_logging.log_debug("ble_bridge", f"[{_ts()}] [BLE-Bridge] Stopping (Ctrl+C)")
        finally:
            try:
                await client.stop_notify(TX_CHAR_UUID)
            except Exception:
                pass

            # Drop this pad from the BLE registry on disconnect.
            try:
                if state.pad_uuid:
                    set_pad_connection(state.pad_uuid, "ble", False)
                    _connected_ble_pads.pop(state.pad_uuid, None)
            except Exception:
                _connected_ble_pads.clear()


async def send_task_app_state_ble(
    pad_uuid: str,
    buttons: List[dict],
    version: Optional[int] = None,
) -> bool:
    """Best-effort send of a task_app_state message to a BLE-connected pad.

    If the pad is not currently connected over BLE, this is a no-op.
    """

    state = _connected_ble_pads.get(pad_uuid)
    if state is None:
        return False

    # Avoid interleaving large config replies with task_app_state lines.
    if state.sending_config:
        return False

    try:
        if not state.client.is_connected:
            return False
    except Exception:
        return False

    msg: dict = {"type": "task_app_state", "buttons": buttons}
    if version is not None:
        msg["version"] = int(version)

    try:
        ok = await _write_ble_json(state, msg)
        if not ok:
            return False
        short_id = pad_uuid[:8]
        print(
            f"[{_ts()}] [BLE-Bridge] Sent task_app_state to pad {short_id}...",
            flush=True,
        )
        return True
    except Exception as e:
        short_id = pad_uuid[:8]
        print(
            f"[{_ts()}] [BLE-Bridge] Failed to send task_app_state to pad {short_id}...: {e}",
            flush=True,
        )
        return False


async def send_display_state_ble(pad_uuid: str, locked: bool) -> bool:
    """Best-effort send of a host_display_state message to a BLE pad.

    This is used to turn pad screens off when the host session is locked and
    back on when the user unlocks the workstation.
    """

    state = _connected_ble_pads.get(pad_uuid)
    if state is None:
        return False

    # Avoid interleaving large config replies with host_display_state lines.
    if state.sending_config:
        return False

    try:
        if not state.client.is_connected:
            return False
    except Exception:
        return False

    msg: dict = {
        "type": "host_display_state",
        "state": "locked" if locked else "unlocked",
    }

    try:
        ok = await _write_ble_json(state, msg)
        if not ok:
            return False
        short_id = pad_uuid[:8]
        from displaypad_server.core.logging import log_debug

        log_debug("power", f"[{_ts()}] [POWER] Sent host_display_state to BLE pad {short_id} (locked={locked})")
        return True
    except Exception as e:
        short_id = pad_uuid[:8]
        from displaypad_server.core.logging import log_debug

        log_debug("power", f"[{_ts()}] [POWER] Failed to send host_display_state to BLE pad {short_id}: {e}")
        return False


async def send_time_update_ble(pad_uuid: str) -> bool:
    state = _connected_ble_pads.get(pad_uuid)
    if state is None:
        return False
    return await _send_time_update(state)


async def send_config_update_pending_ble(pad_uuid: str) -> bool:
    state = _connected_ble_pads.get(pad_uuid)
    if state is None or state.sending_config:
        return False
    try:
        return await _write_ble_json(state, {"type": "config_update_pending"})
    except Exception:
        return False


async def broadcast_display_state_ble(locked: bool, pad_filter: Optional[Set[str]] = None) -> int:
    """Broadcast host_display_state to connected BLE pads.

    If pad_filter is provided, only pads whose UUID is in the set will be
    updated. Returns the number of pads that successfully received the
    update.
    """

    pad_ids = list(_connected_ble_pads.keys())
    sent_count = 0
    for pad_uuid in pad_ids:
        if pad_filter is not None and pad_uuid not in pad_filter:
            continue
        try:
            ok = await send_display_state_ble(pad_uuid, locked)
        except Exception:
            ok = False
        if ok:
            sent_count += 1
    return sent_count


async def run_managed_bridge(
    api_base: str,
    device_name: Optional[str] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Run the BLE bridge in a supervision loop.

    This helper is intended for embedding the bridge inside the main
    DisplayPad API process. It repeatedly calls :func:`run_bridge` to:

    - Scan for PAD-xxxx devices.
    - Connect and service a pad until disconnect or error.
    - On normal return or exceptions, wait briefly and retry, unless a
      stop event has been set.
    """

    backoff_seconds = 2.0

    while True:
        if stop_event is not None and stop_event.is_set():
            print(f"[{_ts()}] [BLE-Bridge] Manager stop requested; exiting", flush=True)
            return

        run_started = _time.time()
        try:
            await run_bridge(api_base=api_base, device_name=device_name)
        except Exception as e:
            print(f"[{_ts()}] [BLE-Bridge] run_bridge error: {e}", flush=True)

        run_duration = _time.time() - run_started
        if run_duration >= 30.0:
            backoff_seconds = 2.0
        else:
            backoff_seconds = min(30.0, backoff_seconds * 1.5)

        if stop_event is not None and stop_event.is_set():
            print(f"[{_ts()}] [BLE-Bridge] Manager stop requested after run; exiting", flush=True)
            return

        # Small delay before scanning/connecting again to avoid tight retry
        # loops when no pads are available or repeated errors occur.
        await asyncio.sleep(backoff_seconds)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DisplayPad BLE GATT bridge")
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:7443",
        help=(
            "Base URL for DisplayPad HTTP API, "
            "default: http://127.0.0.1:7443"
        ),
    )
    parser.add_argument(
        "--device-name",
        default=None,
        help="Exact BLE device name to connect to (e.g. PAD-B49E). "
        "If omitted, the first PAD-xxxx device found is used.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    asyncio.run(run_bridge(api_base=args.api_base, device_name=args.device_name))


if __name__ == "__main__":
    main()
