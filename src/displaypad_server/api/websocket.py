import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, WebSocket

from displaypad_server.core.config import get_config
from displaypad_server.core.pad_runtime import reconcile_pad_runtime, set_pad_connection, update_pad_status
from displaypad_server.db.database import connect

router = APIRouter()

# Registry of active WebSocket connections keyed by pad UUID. This allows
# background tasks (e.g. task keypad process monitor) to push JSON messages
# such as real-time application state updates to specific devices.
connected_pads: Dict[str, WebSocket] = {}


async def send_json_to_pad(pad_uuid: str, message: dict[str, Any]) -> bool:
    ws = connected_pads.get(pad_uuid)
    if ws is None:
        return False
    try:
        await ws.send_json(message)
        return True
    except Exception:
        return False


@router.websocket("/pads/{pad_id}/ws")
async def pad_websocket(websocket: WebSocket, pad_id: str) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "hello", "pad_id": pad_id})

    # Register this connection
    connected_pads[pad_id] = websocket
    set_pad_connection(pad_id, "wifi", True)

    try:
        while True:
            # Wait for messages from the client. Pads currently send:
            #   - log_session_start: begin a new log session for this boot
            #   - log: individual console log lines
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                continue

            msg_type = data.get("type")
            if msg_type in {"log_session_start", "log"}:
                _handle_log_message(pad_id, msg_type, data)
            elif msg_type == "pad_status":
                update_pad_status(pad_id, "wifi", data)
                await reconcile_pad_runtime(pad_id)
    except Exception:
        # Client disconnected or receive error
        pass
    finally:
        # Remove from registry if this is still the current socket
        try:
            existing = connected_pads.get(pad_id)
            if existing is websocket:
                connected_pads.pop(pad_id, None)
        except Exception:
            connected_pads.pop(pad_id, None)
        set_pad_connection(pad_id, "wifi", False)


def _handle_log_message(pad_uuid: str, msg_type: str, data: dict) -> None:
    """Persist log session metadata and log lines for a given pad.

    This is intentionally synchronous and lightweight; log volumes from
    individual ESP32 devices are expected to be relatively low.
    """

    try:
        config = get_config()
        now = datetime.now(timezone.utc).isoformat()

        with connect(config.database_path) as conn:
            # Resolve pad_id once for the given pad_uuid
            cur = conn.execute(
                "SELECT id FROM pads WHERE pad_uuid = ?",
                (pad_uuid,),
            )
            row = cur.fetchone()
            if not row:
                return
            pad_id = row["id"]

            if msg_type == "log_session_start":
                session_uuid = str(data.get("session_uuid") or "").strip()
                if not session_uuid:
                    return

                reboot_reason = data.get("boot_reason") or None
                fw_version = data.get("fw_version") or None

                # Close any previously open sessions for this pad
                conn.execute(
                    "UPDATE log_sessions SET ended_at = ? WHERE pad_id = ? AND ended_at IS NULL",
                    (now, pad_id),
                )

                conn.execute(
                    """
                    INSERT INTO log_sessions (pad_id, pad_uuid, session_uuid, started_at, reboot_reason, fw_version)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (pad_id, pad_uuid, session_uuid, now, reboot_reason, fw_version),
                )
                conn.commit()
                return

            if msg_type == "log":
                session_uuid = str(data.get("session_uuid") or "").strip()
                if not session_uuid:
                    return

                # Find the current session for this pad/session_uuid
                cur = conn.execute(
                    """
                    SELECT id FROM log_sessions
                    WHERE pad_id = ? AND session_uuid = ?
                    ORDER BY started_at DESC LIMIT 1
                    """,
                    (pad_id, session_uuid),
                )
                sess = cur.fetchone()
                if not sess:
                    # If we don't have a session, create one on the fly.
                    conn.execute(
                        """
                        INSERT INTO log_sessions (pad_id, pad_uuid, session_uuid, started_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (pad_id, pad_uuid, session_uuid, now),
                    )
                    session_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
                else:
                    session_id = sess["id"]

                seq = int(data.get("seq") or 0)
                level = data.get("level") or None
                message = str(data.get("message") or "")

                conn.execute(
                    """
                    INSERT INTO logs (session_id, pad_id, pad_uuid, seq, created_at, level, message)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, pad_id, pad_uuid, seq, now, level, message),
                )
                conn.commit()
    except Exception:
        # Logging should never break the WebSocket flow; failures here are
        # intentionally swallowed.
        return
