from pathlib import Path

import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from displaypad_server.api import (
    pairing,
    pads,
    buttons,
    macros,
    tasks,
    websocket,
    discovery as discovery_api,
    icons as icons_api,
    application_icons as app_icons_api,
)
from displaypad_server.core.discovery import discovery_service
from displaypad_server.core.config import get_config, get_api_identity
from displaypad_server.core import logging as dp_logging
from displaypad_server.core.icons_sync import sync_icons_from_folder
from displaypad_server.db.database import connect
from displaypad_server.windows.processes import list_running_executables
import base64

# Path to static files
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="DisplayPad Server",
        version="0.1.0",
        description="Windows-only API for ESP32 touchscreen DisplayPads",
    )

    # API routes
    # Legacy PIN-based pairing has been replaced by discovery/auto-assign.
    app.include_router(pads.router, prefix="/api/v1/pads", tags=["pads"])
    app.include_router(buttons.router, prefix="/api/v1/buttons", tags=["buttons"])
    app.include_router(macros.router, prefix="/api/v1/macros", tags=["macros"])
    app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
    app.include_router(websocket.router, prefix="/api/v1", tags=["websocket"])
    app.include_router(discovery_api.router, prefix="/api/v1/discovery", tags=["discovery"])
    app.include_router(icons_api.router, prefix="/api/v1", tags=["icons"])
    app.include_router(app_icons_api.router, prefix="/api/v1", tags=["application-icons"])

    async def _task_keypad_monitor() -> None:
        """Background task to keep Task Keypads in sync with running apps.

        This periodically scans running executables on the Windows host,
        matches them to Launch Application buttons on pads configured in
        "task_keypad" mode, and pushes a compact "task_app_state" message
        over WebSocket to any connected pads so they can update their
        Task Keypad display in real time.
        """

        # Lazy import to avoid circular dependencies at module import time.
        from displaypad_server.api import websocket as ws_module

        # Cache of last sent state per pad_uuid and last WebSocket object we
        # delivered to. This lets us:
        #   - Only send when an app's running state actually changes.
        #   - Still send a full snapshot once when a pad connects or
        #     reconnects (new WebSocket object), so reboots get the current
        #     state even if no apps changed since.
        last_state: dict[str, dict[int, bool]] = {}
        last_ws_id: dict[str, int] = {}

        while True:
            try:
                await asyncio.sleep(1.0)

                # Collect running executables on this host. We keep track of
                # both full normalized paths and simple basenames so that
                # buttons configured with just "edge.exe" or similar still
                # match the actual running processes.
                running = list_running_executables()
                if not running:
                    norm_running_paths: set[str] = set()
                    norm_running_names: set[str] = set()
                else:
                    from pathlib import Path as _Path

                    norm_running_paths: set[str] = set()
                    norm_running_names: set[str] = set()
                    for p in running:
                        if not p:
                            continue
                        try:
                            resolved = _Path(p).resolve()
                            norm_path = str(resolved).lower()
                            norm_name = resolved.name.lower()
                        except Exception:
                            norm_path = p.lower()
                            try:
                                norm_name = _Path(p).name.lower()
                            except Exception:
                                norm_name = p.lower()

                        norm_running_paths.add(norm_path)
                        norm_running_names.add(norm_name)

                cfg = get_config()

                # Build current state across all task_keypad pads.
                current_state: dict[str, dict[int, bool]] = {}
                with connect(cfg.database_path) as conn:
                    cursor = conn.execute(
                        """
                        SELECT id, pad_uuid, mode
                        FROM pads
                        WHERE enabled = 1 AND revoked = 0
                        """
                    )
                    pads = cursor.fetchall()

                    for pad_row in pads:
                        if pad_row["mode"] != "task_keypad":
                            continue

                        pad_db_id = pad_row["id"]
                        pad_uuid = pad_row["pad_uuid"]

                        # For this pad, load all enabled buttons that have an
                        # executable_path snapshot; other button types are
                        # ignored for Task Keypad presence.
                        bcur = conn.execute(
                            """
                            SELECT slot, executable_path
                            FROM buttons
                            WHERE pad_id = ? AND enabled = 1 AND executable_path IS NOT NULL
                            """,
                            (pad_db_id,),
                        )
                        btn_rows = bcur.fetchall()

                        state_for_pad: dict[int, bool] = {}
                        from pathlib import Path as _Path2

                        # Ensure each application appears at most once on a
                        # Task Keypad, even if multiple buttons are configured
                        # with the same executable snapshot. We deduplicate by
                        # normalized executable path/name and prefer the
                        # lowest slot number (ORDER BY slot above).
                        seen_app_keys: set[str] = set()

                        for b in btn_rows:
                            exe = b["executable_path"] or ""
                            if not exe:
                                continue

                            try:
                                exe_path = _Path2(exe).resolve()
                                norm_exe_path = str(exe_path).lower()
                                norm_exe_name = exe_path.name.lower()
                            except Exception:
                                norm_exe_path = exe.lower()
                                try:
                                    norm_exe_name = _Path2(exe).name.lower()
                                except Exception:
                                    norm_exe_name = exe.lower()

                            app_key = norm_exe_path or norm_exe_name

                            running_now = (
                                norm_exe_path in norm_running_paths
                                or norm_exe_name in norm_running_names
                            )

                            # If we've already mapped this application to a
                            # slot on this pad, keep additional buttons for
                            # the same exe hidden in Task Keypad mode.
                            if app_key in seen_app_keys:
                                running_now = False
                            elif running_now:
                                seen_app_keys.add(app_key)

                            slot = int(b["slot"])
                            state_for_pad[slot] = running_now

                            # Lightweight debug so we can understand why a
                            # given Task Keypad button is or is not marked as
                            # running when troubleshooting. Gated behind the
                            # "task_keypad" debug category to avoid flooding
                            # the console when disabled.
                            dp_logging.log_debug(
                                "task_keypad",
                                f"[TaskKeypad] pad={pad_uuid[:8]} slot={slot} "
                                f"exe={exe!r} name={norm_exe_name!r} "
                                f"running={running_now}",
                            )

                        current_state[pad_uuid] = state_for_pad

                # Push updates to any connected pads only when state changed
                # or when the WebSocket connection is new for that pad. This
                # means each app going on/off results in a single push, and a
                # pad (or server) reboot triggers one full snapshot.
                for pad_uuid, state in current_state.items():
                    ws = ws_module.connected_pads.get(pad_uuid)
                    if ws is None:
                        dp_logging.log_debug(
                            "task_keypad",
                            f"[TaskKeypad] no active websocket for pad {pad_uuid[:8]} - "
                            "skipping task_app_state send",
                        )
                        continue

                    prev_state = last_state.get(pad_uuid)
                    prev_ws = last_ws_id.get(pad_uuid)
                    current_ws = id(ws)

                    # If both the app-running state and the WebSocket object
                    # are unchanged, we can safely skip sending.
                    if prev_state == state and prev_ws == current_ws:
                        dp_logging.log_debug(
                            "task_keypad",
                            f"[TaskKeypad] skipping send for {pad_uuid[:8]} - "
                            f"state unchanged and same websocket (id={current_ws})",
                        )
                        continue

                    try:
                        buttons_payload = [
                            {"slot": int(slot), "running": bool(running)}
                            for slot, running in sorted(state.items())
                        ]

                        # Debug: log when we actually push a task_app_state
                        # message, and whether this was due to a state change
                        # or a new WebSocket connection for the pad. Gated
                        # behind the Task Keypad debug category.
                        reason_parts: list[str] = []
                        if prev_state != state:
                            reason_parts.append("state_changed")
                        if prev_ws != current_ws:
                            reason_parts.append("new_ws")
                        reason = ",".join(reason_parts) or "unknown"
                        dp_logging.log_debug(
                            "task_keypad",
                            f"[TaskKeypad] sending task_app_state to {pad_uuid[:8]} "
                            f"reason={reason} payload={buttons_payload}",
                        )

                        await ws.send_json({
                            "type": "task_app_state",
                            "buttons": buttons_payload,
                        })
                        last_state[pad_uuid] = state
                        last_ws_id[pad_uuid] = current_ws
                    except Exception as e:  # pragma: no cover - best-effort logging
                        print(f"[TaskKeypad] Failed to send state to {pad_uuid[:16]}...: {e}", flush=True)

            except Exception as e:  # pragma: no cover - keep monitor alive
                print(f"[TaskKeypad] Monitor loop error: {e}", flush=True)

    @app.on_event("startup")
    async def startup_event():
        """Start UDP discovery, sync icons, re-send assignments, and start monitors."""
        discovery_service.start()

        # Sync icons table with icons folder so /api/v1/icons reflects
        # the actual set of PNGs available on disk.
        try:
            sync_icons_from_folder()
        except Exception as e:
            print(f"[Startup] Failed to sync icons: {e}")

        # On startup, attempt to re-send ASSIGN packets to any pads we know
        # about from the database, using their last known IP and stored
        # device tokens. This helps devices reconnect without having to
        # re-run the full discovery/assignment flow after a server restart.
        try:
            config = get_config()
            identity = get_api_identity(config.database_path)

            with connect(config.database_path) as conn:
                cursor = conn.execute(
                    """
                    SELECT pad_uuid, encrypted_token, last_ip
                    FROM pads
                    WHERE enabled = 1 AND revoked = 0
                          AND encrypted_token IS NOT NULL
                          AND last_ip IS NOT NULL
                    """
                )
                rows = cursor.fetchall()

            for row in rows:
                pad_uuid = row["pad_uuid"]
                last_ip = row["last_ip"]
                enc = row["encrypted_token"]

                try:
                    encryption_key = identity.api_secret[:32].encode()
                    encrypted_bytes = base64.b64decode(enc)
                    device_token = bytes([
                        b ^ encryption_key[i % len(encryption_key)]
                        for i, b in enumerate(encrypted_bytes)
                    ]).decode()
                except Exception as e:
                    print(f"[Startup] Failed to decrypt token for {pad_uuid}: {e}")
                    continue

                if not last_ip:
                    continue

                print(f"[Startup] Re-sending ASSIGN to {pad_uuid[:16]}... at {last_ip}")
                discovery_service.assign_pad_to_ip(
                    pad_uuid,
                    last_ip,
                    device_token,
                    identity.api_uuid,
                    config.api_port,
                )
        except Exception as e:
            print(f"[Startup] Error while resending assignments: {e}")

        # Start background monitor for Task Keypad app state (fire-and-forget)
        try:
            asyncio.create_task(_task_keypad_monitor())
        except Exception as e:
            print(f"[Startup] Failed to start Task Keypad monitor: {e}", flush=True)

    @app.on_event("shutdown")
    async def shutdown_event():
        """Stop UDP discovery service."""
        discovery_service.stop()

    # Static files (if directory exists)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": "DisplayPad Server"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        """Simple dashboard landing page."""
        return """
<!DOCTYPE html>
<html>
<head>
    <title>DisplayPad Server</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        h1 { color: #0078d4; }
        .card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin: 20px 0;
        }
        .status { color: #107c10; font-weight: bold; }
        code {
            background: #f0f0f0;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: Consolas, monospace;
        }
    </style>
</head>
<body>
    <h1>DisplayPad Server</h1>
    <div class="card">
        <p>Status: <span class="status">Running</span></p>
        <p>API Version: 0.1.0</p>
        <p>Use the system tray menu to manage your DisplayPads.</p>
    </div>
    <div class="card">
        <h2>Quick Start</h2>
        <ol>
            <li>Power on your ESP32 DisplayPad on the same network as this PC.</li>
            <li>The device will automatically discover and register with this server.</li>
            <li>Use the GUI to select the keypad and configure its buttons.</li>
        </ol>
    </div>
    <div class="card">
        <h2>API Endpoints</h2>
        <ul>
            <li><code>POST /api/v1/discovery/hello</code> - Device announces itself</li>
            <li><code>POST /api/v1/discovery/assign</code> - Server assigns device token</li>
            <li><code>GET /api/v1/pads/{id}/config</code> - Get pad configuration</li>
            <li><code>POST /api/v1/pads/{id}/config</code> - Save pad configuration</li>
            <li><code>POST /api/v1/pads/{id}/press</code> - Button press event</li>
        </ul>
    </div>
</body>
</html>
        """

    return app


app = create_app()
