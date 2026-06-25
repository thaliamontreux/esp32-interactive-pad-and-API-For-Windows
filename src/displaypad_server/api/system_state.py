import ctypes
import sys
from ctypes import wintypes
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from displaypad_server.api import websocket as ws_module
from displaypad_server.ble_bluetooth_bridge import broadcast_display_state_ble
from displaypad_server.core.config import get_config
from displaypad_server.core.logging import log_debug
from displaypad_server.db.database import connect


class HostSessionState(BaseModel):
    locked: bool


router = APIRouter()
_last_reported_locked = False

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _OpenInputDesktop = _user32.OpenInputDesktop
    _OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _OpenInputDesktop.restype = wintypes.HDESK
    _CloseDesktop = _user32.CloseDesktop
    _CloseDesktop.argtypes = [wintypes.HDESK]
    _CloseDesktop.restype = wintypes.BOOL
    _DESKTOP_SWITCHDESKTOP = 0x0100


def get_current_host_session_locked() -> bool:
    if sys.platform == "win32":
        try:
            hdesk = _OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
            if not hdesk:
                return True
            _CloseDesktop(hdesk)
            return False
        except Exception:
            pass
    return _last_reported_locked


@router.get("/system/host_session_state")
async def get_host_session_state() -> dict:
    locked = bool(get_current_host_session_locked())
    return {"locked": locked}


@router.post("/system/host_session_state")
async def update_host_session_state(payload: HostSessionState) -> dict:
    global _last_reported_locked
    locked = bool(payload.locked)
    _last_reported_locked = locked
    state_value: Literal["locked", "unlocked"] = "locked" if locked else "unlocked"
    message = {"type": "host_display_state", "state": state_value}
    
    # Look up pads that have opted in to blanking on lock. If the column is
    # missing for any reason, default to broadcasting to all connected pads.
    try:
        config = get_config()
        with connect(config.database_path) as conn:
            cur = conn.execute(
                """
                SELECT pad_uuid FROM pads
                WHERE enabled = 1 AND revoked = 0 AND blank_on_lock = 1
                """
            )
            rows = cur.fetchall()
        allowed_pad_uuids = {str(r["pad_uuid"]) for r in rows}
    except Exception:
        allowed_pad_uuids = None

    target_count = 0
    if allowed_pad_uuids is None:
        target_count = len(ws_module.connected_pads)
    else:
        target_count = sum(1 for pad_uuid in ws_module.connected_pads.keys() if pad_uuid in allowed_pad_uuids)

    log_debug(
        "power",
        f"[POWER] Host session state changed to {state_value} (locked={locked}) - targeting {target_count} WiFi pads and broadcasting to all BLE pads",
    )

    # WebSocket (WiFi) pads
    targets = list(ws_module.connected_pads.items())
    for pad_uuid, ws in targets:
        if allowed_pad_uuids is not None and pad_uuid not in allowed_pad_uuids:
            continue
        try:
            await ws.send_json(message)
        except Exception:
            continue

    # BLE pads: always broadcast to all connected BLE devices. The
    # blank_on_lock filter is currently only enforced for WiFi pads so that
    # Bluetooth-connected devices reliably receive host display state
    # transitions.
    try:
        await broadcast_display_state_ble(locked, None)
    except Exception:
        pass

    return {"locked": locked}
