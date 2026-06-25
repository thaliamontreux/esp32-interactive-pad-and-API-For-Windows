from __future__ import annotations

import copy
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from displaypad_server.core.config import get_config
from displaypad_server.core.timezone_config import get_local_epoch
from displaypad_server.db.database import connect

_lock = RLock()
_pad_runtime: dict[str, dict[str, Any]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _send_wifi_message(pad_uuid: str, message: dict[str, Any]) -> bool:
    from displaypad_server.api import websocket as ws_module

    return await ws_module.send_json_to_pad(pad_uuid, message)


async def _send_ble_config_update(pad_uuid: str) -> bool:
    from displaypad_server.ble_bluetooth_bridge import send_config_update_pending_ble

    return await send_config_update_pending_ble(pad_uuid)


async def _send_ble_time_update(pad_uuid: str) -> bool:
    from displaypad_server.ble_bluetooth_bridge import send_time_update_ble

    return await send_time_update_ble(pad_uuid)


async def _send_ble_display_state(pad_uuid: str, locked: bool) -> bool:
    from displaypad_server.ble_bluetooth_bridge import send_display_state_ble

    return await send_display_state_ble(pad_uuid, locked)


async def _send_ble_task_state(pad_uuid: str, buttons: list[dict[str, Any]], version: int | None) -> bool:
    from displaypad_server.ble_bluetooth_bridge import send_task_app_state_ble

    return await send_task_app_state_ble(pad_uuid, buttons, version)


def _ensure_state(pad_uuid: str) -> dict[str, Any]:
    state = _pad_runtime.get(pad_uuid)
    if state is None:
        state = {
            "pad_uuid": pad_uuid,
            "last_seen_at": None,
            "last_reported_at": None,
            "wifi_connected": False,
            "ble_connected": False,
            "last_transport": None,
            "runtime": None,
            "expected_task_slots": [],
            "expected_task_version": None,
            "last_reconciled_at": None,
            "last_corrections": [],
        }
        _pad_runtime[pad_uuid] = state
    return state


def set_pad_connection(pad_uuid: str, transport: str, connected: bool) -> dict[str, Any]:
    with _lock:
        state = _ensure_state(pad_uuid)
        now = _utc_now()
        state["last_seen_at"] = now
        if transport == "wifi":
            state["wifi_connected"] = bool(connected)
        elif transport in {"ble", "bluetooth"}:
            state["ble_connected"] = bool(connected)
        if connected:
            state["last_transport"] = transport
        return copy.deepcopy(state)


def update_pad_status(pad_uuid: str, transport: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        state = _ensure_state(pad_uuid)
        now = _utc_now()
        state["last_seen_at"] = now
        state["last_reported_at"] = now
        state["last_transport"] = transport
        state["runtime"] = dict(payload)
        if transport == "wifi":
            state["wifi_connected"] = True
        elif transport in {"ble", "bluetooth"}:
            state["ble_connected"] = True
        return copy.deepcopy(state)


def set_expected_task_state(pad_uuid: str, active_slots: list[int], version: int | None = None) -> dict[str, Any]:
    with _lock:
        state = _ensure_state(pad_uuid)
        state["expected_task_slots"] = sorted({int(slot) for slot in active_slots if int(slot) > 0})
        state["expected_task_version"] = int(version) if version is not None else None
        state["last_seen_at"] = _utc_now()
        return copy.deepcopy(state)


def note_reconciliation(pad_uuid: str, corrections: list[str]) -> None:
    with _lock:
        state = _ensure_state(pad_uuid)
        state["last_reconciled_at"] = _utc_now()
        state["last_corrections"] = list(corrections)


def get_pad_runtime_snapshot(pad_uuid: str) -> dict[str, Any] | None:
    with _lock:
        state = _pad_runtime.get(pad_uuid)
        if state is None:
            return None
        return copy.deepcopy(state)


def list_pad_runtime_snapshots() -> list[dict[str, Any]]:
    with _lock:
        return [copy.deepcopy(state) for state in _pad_runtime.values()]


async def reconcile_pad_runtime(pad_uuid: str) -> list[str]:
    from displaypad_server.api.system_state import get_current_host_session_locked
    from displaypad_server.ble_bluetooth_bridge import request_task_app_state_snapshot

    snapshot = get_pad_runtime_snapshot(pad_uuid)
    if not snapshot:
        return []

    runtime = snapshot.get("runtime") or {}
    if not runtime:
        return []

    corrections: list[str] = []

    with connect(get_config().database_path) as conn:
        row = conn.execute(
            "SELECT mode, config_version FROM pads WHERE pad_uuid = ?",
            (pad_uuid,),
        ).fetchone()

    desired_mode = row["mode"] if row else None
    desired_config_version = int(row["config_version"]) if row and row["config_version"] is not None else None

    actual_locked = bool(get_current_host_session_locked())
    reported_locked = bool(runtime.get("host_locked", False))
    if actual_locked != reported_locked:
        message = {"type": "host_display_state", "state": "locked" if actual_locked else "unlocked"}
        wifi_sent = await _send_wifi_message(pad_uuid, message)
        ble_sent = await _send_ble_display_state(pad_uuid, actual_locked)
        if wifi_sent or ble_sent:
            corrections.append("host_display_state")

    reported_config_version = runtime.get("config_version")
    reported_mode = runtime.get("pad_mode")
    if desired_config_version is not None and (
        reported_config_version is None or int(reported_config_version) != desired_config_version or (desired_mode and reported_mode and reported_mode != desired_mode)
    ):
        wifi_sent = await _send_wifi_message(pad_uuid, {"type": "config_update_pending"})
        ble_sent = await _send_ble_config_update(pad_uuid)
        if wifi_sent or ble_sent:
            corrections.append("config_update_pending")

    reported_epoch = runtime.get("epoch")
    if reported_epoch is not None:
        try:
            reported_epoch_value = int(reported_epoch)
        except Exception:
            reported_epoch_value = 0
        if reported_epoch_value > 0 and abs(get_local_epoch() - reported_epoch_value) > 90:
            time_message = {"type": "time", "epoch": get_local_epoch()}
            wifi_sent = await _send_wifi_message(pad_uuid, time_message)
            ble_sent = await _send_ble_time_update(pad_uuid)
            if wifi_sent or ble_sent:
                corrections.append("time")

    if desired_mode == "task_keypad":
        expected_slots = set(int(slot) for slot in snapshot.get("expected_task_slots") or [])
        reported_slots = set(int(slot) for slot in runtime.get("active_task_slots") or [])
        version = snapshot.get("expected_task_version")
        if expected_slots != reported_slots:
            buttons_payload = [{"slot": slot, "running": True} for slot in sorted(expected_slots)]
            wifi_sent = await _send_wifi_message(
                pad_uuid,
                {"type": "task_app_state", "buttons": buttons_payload, "version": version},
            )
            ble_sent = await _send_ble_task_state(pad_uuid, buttons_payload, version)
            if wifi_sent or ble_sent:
                corrections.append("task_app_state")
        elif version is None:
            request_task_app_state_snapshot(pad_uuid)

    note_reconciliation(pad_uuid, corrections)
    return corrections
