"""Pad device configuration endpoints."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel

from displaypad_server.core.config import get_config, get_api_identity
from displaypad_server.core.crypto import hmac_verify, hmac_sign, verify_secret
from displaypad_server.core.security import validate_timestamp, check_and_store_nonce, redact_secret
from displaypad_server.core.layout import generate_layout, ButtonRect
from displaypad_server.db.database import connect

router = APIRouter()


class ScreenConfig(BaseModel):
    width: int
    height: int
    rotation: int = 0


class LayoutConfig(BaseModel):
    columns: int
    rows: int


class ButtonConfig(BaseModel):
    page: int = 1
    slot: int  # slot index within the page (1..button_count)
    x: int
    y: int
    w: int
    h: int
    label: str
    icon_id: str | None = None
    action_id: str | None = None
    # Colors are stored as optional hex strings (e.g. "#RRGGBB").
    bg_color: str | None = None
    icon_color: str | None = None
    text_color: str | None = None
    show_text: bool = True
    # Optional application icon information for "Launch Application" actions.
    application_id: int | None = None
    has_application_icon: bool = False
    # Optional version/hash for the application icon so firmware can
    # invalidate its local cache when the icon file changes.
    application_icon_version: str | None = None


class ControlPanelPINPolicy(BaseModel):
    enabled: bool
    pin_length: int
    pin_hash: str
    default_pin_active: bool
    max_attempts: int
    lockout_seconds: int


class TimeConfig(BaseModel):
    """Per-pad time display configuration for the ESP32 top bar."""

    use_24h: bool = False
    show_am_pm: bool = True
    # Offset in minutes from UTC for the API host's local timezone. The ESP32
    # uses this to render its taskbar clock in the same timezone as the
    # system running the DisplayPad API.
    timezone_offset_minutes: int = 0


class PadConfigResponse(BaseModel):
    pad_id: str
    name: str
    pad_mode: str
    button_count: int
    page_count: int
    page_button_counts: list[int] | None = None
    config_version: int
    control_panel_pin: ControlPanelPINPolicy
    screen: ScreenConfig
    layout: LayoutConfig
    time: TimeConfig
    buttons: list[ButtonConfig]


class ConfigVersionResponse(BaseModel):
    pad_id: str
    config_version: int
    updated_at: str
    update_required: bool


class ConfigAppliedRequest(BaseModel):
    config_version: int
    status: str = "applied"


class ButtonPressRequest(BaseModel):
    slot: int
    press_type: str = "tap"


def _auto_register_pad(pad_id: str, signature: str, message: str) -> dict:
    """Auto-register/update a pad when auth fails - applies default config."""
    from displaypad_server.core.crypto import generate_secure_token, hash_secret
    import base64

    print(f"[AUTO_REG] Auto-registering pad: {pad_id}", flush=True)

    config = get_config()
    identity = get_api_identity(config.database_path)
    now = datetime.now(timezone.utc).isoformat()

    # Generate new device token (32 bytes = ~43 chars base64)
    device_token = generate_secure_token(32)

    # Encrypt token for storage
    encryption_key = identity.api_secret[:32].encode()
    encrypted_token = bytes([b ^ encryption_key[i % len(encryption_key)] for i, b in enumerate(device_token.encode())])
    encrypted_token_b64 = base64.b64encode(encrypted_token).decode()

    # Default PIN hash
    default_pin_hash = hash_secret(config.default_control_panel_pin)

    with connect(config.database_path) as conn:
        # Check if pad exists
        cursor = conn.execute(
            "SELECT id, encrypted_token FROM pads WHERE pad_uuid = ?",
            (pad_id,)
        )
        existing = cursor.fetchone()

        if existing:
            # Update existing pad with new token
            conn.execute(
                """
                UPDATE pads SET
                    encrypted_token = ?,
                    token_hash = ?,
                    last_seen = ?,
                    enabled = 1,
                    revoked = 0,
                    control_panel_pin_hash = ?,
                    default_pin_active = 1,
                    config_version = 1
                WHERE pad_uuid = ?
                """,
                (
                    encrypted_token_b64, hash_secret(device_token)[:32], now,
                    default_pin_hash, pad_id
                )
            )
            print(f"[AUTO_REG] Updated existing pad with new token", flush=True)
        else:
            # Create new pad
            pad_uuid_short = pad_id.replace('pad-', '')[:8]
            conn.execute(
                """
                INSERT INTO pads (
                    pad_uuid, name, mode, screen_width, screen_height, screen_driver,
                    button_count, token_hash, encrypted_token, paired_at, last_seen,
                    enabled, revoked, config_version, control_panel_pin_hash, default_pin_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pad_id, f"Pad-{pad_uuid_short}", 'button_pad',
                    320, 240, 'ILI9341',
                    6, hash_secret(device_token)[:32], encrypted_token_b64,
                    now, now, 1, 0, 1, default_pin_hash, 1
                )
            )
            print(f"[AUTO_REG] Created new pad", flush=True)

        # Mark that a new configuration is available for this pad so that
        # connected devices know to pull the update.
        conn.execute(
            "UPDATE pads SET update_pending = 1, update_required = 1 WHERE id = ?",
            (pad_internal_id,)
        )

        conn.commit()

        # Get the pad ID for button setup
        cursor = conn.execute("SELECT id FROM pads WHERE pad_uuid = ?", (pad_id,))
        row = cursor.fetchone()
        pad_internal_id = row["id"]

        # Create default buttons if none exist
        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM buttons WHERE pad_id = ?",
            (pad_internal_id,)
        )
        button_count = cursor.fetchone()["count"]

        if button_count == 0:
            # Create 6 default buttons
            default_buttons = [
                (1, "Play", "play", "macro_play"),
                (2, "Stop", "stop", "macro_stop"),
                (3, "Vol Up", "volume_up", "macro_vol_up"),
                (4, "Vol Down", "volume_down", "macro_vol_down"),
                (5, "Mute", "mute", "macro_mute"),
                (6, "Config", "gear", "control_panel"),
            ]
            for slot, label, icon, action in default_buttons:
                conn.execute(
                    """
                    INSERT INTO buttons (pad_id, slot, label, icon_id, action_id, enabled)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (pad_internal_id, slot, label, icon, action)
                )
            conn.commit()
            print(f"[AUTO_REG] Applied default button configuration", flush=True)

    return {
        "id": pad_internal_id if 'pad_internal_id' in dir() else 0,
        "pad_uuid": pad_id,
        "auto_registered": True,
        "device_token": device_token,
    }


def _authenticate_pad_simple(pad_id: str, device_token: str) -> dict:
    """Authenticate pad using simple device token comparison (no HMAC, no timestamps)."""
    import base64
    print(f"\n[AUTH] === Simple auth for {pad_id} ===", flush=True)
    config = get_config()
    identity = get_api_identity(config.database_path)

    with connect(config.database_path) as conn:
        cursor = conn.execute(
            "SELECT id, encrypted_token, enabled, revoked FROM pads WHERE pad_uuid = ?",
            (pad_id,)
        )
        pad = cursor.fetchone()

    if not pad:
        print(f"[AUTH] Pad not found - Auto-registering new pad", flush=True)
        return _auto_register_pad(pad_id, device_token, "")

    if not pad["enabled"]:
        print(f"[AUTH] FAILED: Pad disabled", flush=True)
        raise HTTPException(status_code=403, detail="Pad disabled")

    if pad["revoked"]:
        print(f"[AUTH] FAILED: Pad revoked", flush=True)
        raise HTTPException(status_code=403, detail="Pad revoked")

    # Decrypt the device token from database
    stored_token = None
    if pad["encrypted_token"]:
        try:
            encryption_key = identity.api_secret[:32].encode()
            encrypted_bytes = base64.b64decode(pad["encrypted_token"])
            stored_token = bytes([b ^ encryption_key[i % len(encryption_key)] for i, b in enumerate(encrypted_bytes)]).decode()
            print(f"[AUTH] Stored token (first 8 chars): {stored_token[:8]}...", flush=True)
        except Exception as e:
            print(f"[AUTH] Failed to decrypt token: {e}", flush=True)

    # Simple token comparison
    if stored_token and device_token == stored_token:
        print(f"[AUTH] SUCCESS - Token matched", flush=True)
        return dict(pad)

    print(f"[AUTH] Token mismatch or missing - Auto-registering", flush=True)
    return _auto_register_pad(pad_id, device_token, "")


@router.get("/", response_model=dict)
def list_pads() -> dict:
    """List all registered pads."""
    config = get_config()

    with connect(config.database_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, pad_uuid, name, mode, screen_width, screen_height,
                   button_count, enabled, last_seen, config_version
            FROM pads ORDER BY last_seen DESC
            """
        )
        pads = [dict(row) for row in cursor.fetchall()]

    return {"pads": pads}


@router.get("/{pad_id}/config/version", response_model=ConfigVersionResponse)
def get_config_version(
    pad_id: str,
    x_pad_uuid: str = Header(...),
    x_device_token: str = Header(...),
) -> ConfigVersionResponse:
    """Get current config version for a pad."""
    pad = _authenticate_pad_simple(x_pad_uuid, x_device_token)

    with connect(get_config().database_path) as conn:
        cursor = conn.execute(
            """
            SELECT config_version, update_pending, update_required, last_seen
            FROM pads WHERE id = ?
            """,
            (pad["id"],)
        )
        row = cursor.fetchone()

    # Update last_seen; failures here should not break the endpoint.
    now = datetime.now(timezone.utc).isoformat()
    try:
        with connect(get_config().database_path) as conn:
            conn.execute(
                "UPDATE pads SET last_seen = ? WHERE id = ?",
                (now, pad["id"]),
            )
    except Exception as e:  # pragma: no cover - best-effort logging only
        print(f"[Pads] Failed to update last_seen for pad {pad['id']}: {e}", flush=True)

    return ConfigVersionResponse(
        pad_id=pad_id,
        config_version=row["config_version"],
        updated_at=row["last_seen"] or now,
        update_required=bool(row["update_pending"] or row["update_required"]),
    )


@router.get("/{pad_id}/config", response_model=PadConfigResponse)
def get_pad_config(
    pad_id: str,
    x_pad_uuid: str | None = Header(default=None),
    x_device_token: str | None = Header(default=None),
) -> PadConfigResponse:
    """Get full configuration for a pad."""
    config = get_config()

    # If headers are present, authenticate (ESP32 path). Otherwise, allow
    # local GUI access based on pad_id only.
    if x_pad_uuid and x_device_token:
        pad = _authenticate_pad_simple(x_pad_uuid, x_device_token)
        pad_internal_id = pad["id"]
    else:
        with connect(config.database_path) as conn:
            cursor = conn.execute(
                "SELECT id FROM pads WHERE pad_uuid = ?",
                (pad_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Pad not found")
            # Internal numeric pad ID for subsequent queries
            pad_internal_id = row["id"]

    with connect(config.database_path) as conn:
        # Get pad details
        cursor = conn.execute(
            """
            SELECT name,
                   mode,
                   button_count,
                   page_count,
                   page_button_counts,
                   screen_width,
                   screen_height,
                   config_version,
                   control_panel_pin_hash,
                   control_panel_pin_length,
                   default_pin_active,
                   pin_max_attempts,
                   pin_lockout_seconds,
                   time_use_24h,
                   time_show_am_pm
            FROM pads WHERE id = ?
            """,
            (pad_internal_id,)
        )
        pad_row = cursor.fetchone()

        # Get buttons for this pad, including any associated application_id
        cursor = conn.execute(
            """
            SELECT slot,
                   label,
                   icon_id,
                   action_id,
                   bg_color,
                   icon_color,
                   text_color,
                   show_text,
                   application_id,
                   executable_path
            FROM buttons WHERE pad_id = ? AND enabled = 1
            ORDER BY slot
            """,
            (pad_internal_id,)
        )
        buttons = cursor.fetchall()

    # Determine per-page button counts for layout
    import json as _json
    width, height = pad_row["screen_width"], pad_row["screen_height"]
    legacy_per_page = pad_row["button_count"]
    raw_counts = pad_row["page_button_counts"]
    page_counts: list[int] = []
    if raw_counts:
        try:
            page_counts = [max(1, min(32, int(c))) for c in _json.loads(raw_counts)]
        except Exception:
            page_counts = []

    if not page_counts:
        # Legacy fallback: single per-page count, compute pages from max slot
        per_page = legacy_per_page or 6
        max_slot_legacy = max((b["slot"] for b in buttons), default=per_page)
        legacy_page_count = max(1, (max_slot_legacy - 1) // per_page + 1)
        page_counts = [per_page for _ in range(legacy_page_count)]

    page_count = len(page_counts)

    print(
        f"[API] get_pad_config pad_uuid={pad_id} internal_id={pad_internal_id} "
        f"page_counts={page_counts} buttons={len(buttons)}",
        flush=True,
    )

    # Precompute global slot offsets per page
    offsets: list[int] = [0]
    for count in page_counts:
        offsets.append(offsets[-1] + count)

    # Build button configs across all pages
    button_configs: list[ButtonConfig] = []
    button_dict = {b["slot"]: b for b in buttons}

    # Import application icon repository lazily so this endpoint continues
    # working even if the application_icons module is unavailable for some
    # reason. Missing icons simply appear as has_application_icon = False.
    try:  # pragma: no cover - import failure is non-fatal here
        from displaypad_server import application_icons as app_icons_repo  # type: ignore[import]
    except Exception:  # pragma: no cover - best-effort logging only
        app_icons_repo = None  # type: ignore[assignment]

    for page_index, per_page_count in enumerate(page_counts, start=1):
        layout_rects = generate_layout(per_page_count, width, height)
        for rect in layout_rects:
            global_slot = offsets[page_index - 1] + rect.slot
            btn = button_dict.get(global_slot)
            label = btn["label"] if btn else f"Button {rect.slot}"

            # Optional application linkage for Launch Application actions
            application_id = btn["application_id"] if btn else None
            has_app_icon = False
            application_icon_version: str | None = None

            # Prefer explicit application_id when present.
            icon_record = None
            if application_id and app_icons_repo is not None:
                try:
                    icon_record = app_icons_repo.get_primary_icon_for_application(application_id)
                except Exception:  # pragma: no cover - best-effort
                    icon_record = None

            # Fallback: if we still don't have an icon record but we do have
            # an executable_path snapshot, try to locate an icon by that
            # path. This helps older configs where application_id might be
            # NULL but icons were imported based on executables.
            if (
                icon_record is None
                and app_icons_repo is not None
                and btn is not None
                and "executable_path" in btn.keys()
                and btn["executable_path"]
            ):
                try:
                    icon_record = app_icons_repo.get_primary_icon_for_executable(btn["executable_path"])
                    if icon_record is not None and not application_id:
                        # If we located an icon by executable and the button
                        # had no explicit application_id, adopt the
                        # application_id from the icon record so firmware has
                        # a stable ID.
                        application_id = icon_record.application_id
                except Exception:  # pragma: no cover - best-effort
                    icon_record = None

            if icon_record is not None and getattr(icon_record, "icon_path", None):
                # Mirror the path resolution logic used by the
                # /api/v1/application-icons/{application_id}.png endpoint:
                # resolve relative paths under a top-level ./application-icons
                # directory next to data_dir and only treat the icon as
                # present if the file exists.
                icon_path = Path(icon_record.icon_path)
                if not icon_path.is_absolute():
                    project_root = Path(config.data_dir).parent
                    icon_path = project_root / icon_path
                has_app_icon = icon_path.exists() and icon_path.is_file()
                if has_app_icon:
                    # Prefer a stable hash-based version when available;
                    # otherwise fall back to updated_at.
                    version = getattr(icon_record, "icon_hash", None) or getattr(icon_record, "updated_at", None)
                    if version is not None:
                        application_icon_version = str(version)

            raw_icon = btn["icon_id"] if btn else None
            # If this is a Launch Application button that has an imported
            # application icon *and* a non-empty icon_id, treat that as an
            # explicit override to use the macro icon instead of the
            # application PNG on the ESP32.
            if application_id and has_app_icon and raw_icon not in (None, "", "None", "null"):
                has_app_icon = False

            # Normalize legacy values. If there is an associated application
            # icon and no explicit macro icon override, leave icon_id empty so
            # the ESP32 only uses the application PNG. Otherwise, provide a
            # default of 'stars' when no icon set so older macro-style buttons
            # still get a concrete icon.
            if raw_icon in (None, "", "None", "null"):
                if application_id and has_app_icon:
                    icon_id = ""
                else:
                    icon_id = "stars"
            else:
                icon_id = raw_icon

            action_id = btn["action_id"] if btn else None
            bg_color = btn["bg_color"] if btn else None
            icon_color = btn["icon_color"] if btn else None
            text_color = btn["text_color"] if btn else None

            # Default to showing text if the column is missing or NULL
            if btn and "show_text" in btn.keys() and btn["show_text"] is not None:
                show_text = bool(btn["show_text"])
            else:
                show_text = True

            print(
                f"[API] get_pad_config page={page_index} slot={rect.slot} global_slot={global_slot} "
                f"label={label!r} icon_id={icon_id!r} bg_color={bg_color} icon_color={icon_color} "
                f"text_color={text_color} show_text={show_text} application_id={application_id} "
                f"has_app_icon={has_app_icon}",
                flush=True,
            )
            button_configs.append(ButtonConfig(
                page=page_index,
                # Use the global slot index so that button presses and
                # real-time task keypad state updates can address buttons
                # consistently across all pages.
                slot=global_slot,
                x=rect.x,
                y=rect.y,
                w=rect.w,
                h=rect.h,
                label=label,
                icon_id=icon_id,
                action_id=action_id,
                bg_color=bg_color,
                icon_color=icon_color,
                text_color=text_color,
                show_text=show_text,
                application_id=application_id,
                has_application_icon=has_app_icon,
                application_icon_version=application_icon_version,
            ))

    # Calculate layout grid (cols/rows only; gap is implicit in layout) based on
    # the first page's layout; this is mainly informative for control panels.
    from displaypad_server.core.layout import choose_grid
    cols, rows, _ = choose_grid(page_counts[0] if page_counts else legacy_per_page or 6, width, height)

    # Update last_config_downloaded
    now = datetime.now(timezone.utc).isoformat()
    with connect(config.database_path) as conn:
        conn.execute(
            "UPDATE pads SET last_config_downloaded = ?, last_seen = ?, update_pending = 0 WHERE id = ?",
            (pad_row["config_version"], now, pad_internal_id)
        )
        conn.commit()

    # Compute the API host's current UTC offset so devices can render the
    # taskbar clock in the same timezone as the server.
    local_now = datetime.now().astimezone()
    offset = local_now.utcoffset() or timedelta(0)
    timezone_offset_minutes = int(offset.total_seconds() // 60)

    return PadConfigResponse(
        pad_id=pad_id,
        name=pad_row["name"],
        pad_mode=pad_row["mode"],
        button_count=page_counts[0] if page_counts else legacy_per_page or 6,
        page_count=page_count,
        page_button_counts=page_counts,
        config_version=pad_row["config_version"],
        control_panel_pin=ControlPanelPINPolicy(
            enabled=True,
            pin_length=pad_row["control_panel_pin_length"],
            pin_hash=pad_row["control_panel_pin_hash"] or "",
            default_pin_active=bool(pad_row["default_pin_active"]),
            max_attempts=pad_row["pin_max_attempts"],
            lockout_seconds=pad_row["pin_lockout_seconds"],
        ),
        screen=ScreenConfig(width=width, height=height, rotation=0),
        layout=LayoutConfig(columns=cols, rows=rows),
        time=TimeConfig(
            use_24h=bool(pad_row["time_use_24h"] or 0),
            show_am_pm=bool(
                pad_row["time_show_am_pm"]
                if pad_row["time_show_am_pm"] is not None
                else 1
            ),
            timezone_offset_minutes=timezone_offset_minutes,
        ),
        buttons=button_configs,
    )


@router.post("/{pad_id}/config/applied")
def config_applied(
    pad_id: str,
    request: ConfigAppliedRequest,
    x_pad_uuid: str = Header(...),
    x_device_token: str = Header(...),
) -> dict:
    """Confirm config was applied successfully."""
    pad = _authenticate_pad_simple(x_pad_uuid, x_device_token)

    now = datetime.now(timezone.utc).isoformat()

    with connect(get_config().database_path) as conn:
        conn.execute(
            """
            UPDATE pads SET
                last_config_downloaded = ?,
                last_update_status = ?,
                last_update_error = NULL,
                update_pending = 0,
                update_required = 0
            WHERE id = ?
            """,
            (request.config_version, request.status, pad["id"])
        )
        conn.commit()

    return {"applied": True, "config_version": request.config_version}


@router.post("/{pad_id}/press")
def button_press(
    pad_id: str,
    request: ButtonPressRequest,
    x_pad_uuid: str = Header(...),
    x_device_token: str = Header(...),
) -> dict:
    """Handle button press from pad."""
    # Authenticate the request
    pad = _authenticate_pad_simple(x_pad_uuid, x_device_token)

    config = get_config()

    with connect(config.database_path) as conn:
        # Get pad internal ID
        cursor = conn.execute("SELECT id FROM pads WHERE pad_uuid = ?", (pad_id,))
        pad_internal_id = cursor.fetchone()["id"]

        # Get button action and any associated macro / application snapshot
        cursor = conn.execute(
            """
            SELECT
                b.action_id,
                b.application_id,
                b.application_name,
                b.executable_path,
                b.working_directory,
                b.arguments,
                b.override_arguments,
                b.run_mode,
                m.type AS macro_type,
                m.payload_json,
                m.permission_level
            FROM buttons b
            LEFT JOIN macros m ON b.action_id = m.action_id
            WHERE b.pad_id = ? AND b.slot = ? AND b.enabled = 1
            """,
            (pad_internal_id, request.slot),
        )
        row = cursor.fetchone()

    if not row or not row["action_id"]:
        raise HTTPException(status_code=404, detail="Button not configured")

    # Decide what to do based on macro type and/or application snapshot
    executed = False
    action_type: str | None = row["macro_type"] if row["macro_type"] else None

    # First, if this button is bound to a macro, try to execute it.
    if action_type is not None:
        # Debug: log macro information before execution
        try:
            print(
                f"[API] button_press pad_id={pad_id} slot={request.slot} "
                f"action_id={row['action_id']!r} macro_type={row['macro_type']!r}",
                flush=True,
            )
        except Exception:
            pass
        try:
            import json as _json
            from displaypad_server.windows.sendinput import execute_macro

            payload = _json.loads(row["payload_json"] or "{}") if row["payload_json"] else {}
            executed = execute_macro(action_type, payload)
            try:
                print(
                    f"[API] button_press macro executed={executed} pad_id={pad_id} "
                    f"slot={request.slot} action_id={row['action_id']!r}",
                    flush=True,
                )
            except Exception:
                pass
        except Exception as e:  # pragma: no cover - best-effort logging
            print(f"[API] Failed to execute macro for slot {request.slot}: {e}", flush=True)
    else:
        # Debug: explicitly log when no macro is associated with this button.
        try:
            print(
                f"[API] button_press pad_id={pad_id} slot={request.slot} "
                f"action_id={row['action_id']!r} has_no_macro_type",
                flush=True,
            )
        except Exception:
            pass

    # Launch Application: if there is no macro (or it failed / did nothing),
    # fall back to launching a snapshotted application when configured.
    if not executed and row["executable_path"]:
        try:
            from displaypad_server.application_launcher import LaunchSpec, launch_application
            from displaypad_server.windows.windows import bring_window_to_front
            import psutil  # type: ignore[import-not-found]
            # First, try to find an existing process whose executable path OR
            # basename matches our snapshotted path and bring its window to the
            # foreground. This mirrors the Task Keypad monitor logic, which
            # also matches by normalized path or name.
            try:
                target_path_obj = Path(row["executable_path"]).resolve()
                target_path = str(target_path_obj).lower()
                target_name = target_path_obj.name.lower()
            except Exception:
                raw = str(row["executable_path"])
                target_path = raw.lower()
                try:
                    target_name = Path(raw).name.lower()
                except Exception:
                    target_name = raw.lower()

            focused = False
            try:
                for proc in psutil.process_iter(["pid", "exe"]):
                    try:
                        exe = proc.info.get("exe")  # type: ignore[union-attr]
                        if not exe:
                            continue
                        try:
                            proc_path_obj = Path(exe).resolve()
                            proc_path = str(proc_path_obj).lower()
                            proc_name = proc_path_obj.name.lower()
                        except Exception:
                            proc_path = str(exe).lower()
                            try:
                                proc_name = Path(exe).name.lower()
                            except Exception:
                                proc_name = proc_path

                        if proc_path == target_path or proc_name == target_name:
                            try:
                                print(
                                    f"[LAUNCH] Trying to focus existing app pid={proc.info['pid']} "
                                    f"path={proc_path!r} name={proc_name!r}",
                                    flush=True,
                                )
                            except Exception:
                                pass
                            if bring_window_to_front(int(proc.info["pid"])):
                                focused = True
                                try:
                                    print(
                                        f"[LAUNCH] Focused existing application for slot {request.slot}",
                                        flush=True,
                                    )
                                except Exception:
                                    pass
                                break
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
            except Exception as e:
                try:
                    print(f"[LAUNCH] Error while searching for existing process: {e}", flush=True)
                except Exception:
                    pass
                focused = False

            if focused:
                executed = True
                action_type = "focus_existing_application"
            else:
                spec = LaunchSpec(
                    executable_path=row["executable_path"],
                    working_directory=row["working_directory"],
                    arguments=(row["override_arguments"] or row["arguments"] or ""),
                    run_mode=row["run_mode"] or "normal",
                )
                executed = launch_application(spec)
                action_type = "launch_application"
        except Exception as e:  # pragma: no cover - best-effort logging
            print(f"[API] Failed to launch application for slot {request.slot}: {e}", flush=True)

    # Log the button press (and whether we attempted a launch)
    now = datetime.now(timezone.utc).isoformat()
    details = {
        "slot": request.slot,
        "action_id": row["action_id"],
        "press_type": request.press_type,
        "executed": executed,
        "action_type": action_type,
    }
    import json as _json

    with connect(config.database_path) as conn:
        conn.execute(
            """
            INSERT INTO audit_log (pad_id, event_type, details_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                pad_internal_id,
                "button_press",
                _json.dumps(details),
                now,
            ),
        )
        conn.commit()

    return {
        "executed": executed,
        "slot": request.slot,
        "action_id": row["action_id"],
        "action_type": action_type,
    }


class PINChangeRequest(BaseModel):
    current_pin: str
    new_pin: str


class SaveConfigRequest(BaseModel):
    pad_uuid: str
    type: str  # "task" or "macro"
    buttons: list[dict]  # List of button configs
    time_use_24h: bool | None = None
    time_show_am_pm: bool | None = None
    button_count: int | None = None  # legacy single per-page count
    page_count: int | None = None
    page_button_counts: list[int] | None = None


class LogSessionResponse(BaseModel):
    id: int
    session_uuid: str
    started_at: datetime
    ended_at: datetime | None
    reboot_reason: str | None
    fw_version: str | None


class LogEntryResponse(BaseModel):
    id: int
    session_id: int
    seq: int
    created_at: datetime
    level: str | None
    message: str


@router.post("/{pad_id}/config")
def save_pad_config(
    pad_id: str,
    request: SaveConfigRequest,
) -> dict:
    """Save keypad configuration (buttons, type, and time display settings)."""
    config = get_config()

    with connect(config.database_path) as conn:
        # Get internal pad ID and existing layout info
        cursor = conn.execute(
            "SELECT id, button_count FROM pads WHERE pad_uuid = ?",
            (pad_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Pad not found")

        pad_internal_id = row["id"]

        # Derive per-page button counts from request; fall back to legacy
        page_counts: list[int]
        if request.page_button_counts:
            page_counts = [max(1, min(32, int(c))) for c in request.page_button_counts]
        else:
            # Legacy mode: single per-page count, same on all pages actually used
            per_page_count = row["button_count"] or 0
            if request.button_count is not None and request.button_count > 0:
                per_page_count = int(request.button_count)
            if per_page_count <= 0:
                per_page_count = 6
            # Infer how many pages are needed from incoming buttons
            max_page = max((int(b.get("page", 1) or 1) for b in request.buttons), default=1)
            max_page = max(1, min(4, max_page))
            page_counts = [per_page_count for _ in range(max_page)]

        # Clamp page_count to the length of page_counts
        page_count = request.page_count or len(page_counts) or 1
        if page_count < 1:
            page_count = 1
        if page_count > len(page_counts):
            # Pad with the last known count
            last = page_counts[-1] if page_counts else 6
            page_counts.extend([last] * (page_count - len(page_counts)))
        else:
            page_counts = page_counts[:page_count]

        # Resolve time configuration with sane defaults
        use_24h = bool(request.time_use_24h) if request.time_use_24h is not None else False
        show_am_pm = bool(request.time_show_am_pm) if request.time_show_am_pm is not None else True

        print(
            f"[API] save_pad_config pad_uuid={pad_id} internal_id={pad_internal_id} "
            f"requested_buttons={len(request.buttons)} page_counts={page_counts}",
            flush=True,
        )

        # Update pad mode, per-page button count, and time display settings
        mode = "task_keypad" if request.type == "task" else "macro_keypad"
        import json as _json
        page_counts_json = _json.dumps(page_counts)
        conn.execute(
            """
            UPDATE pads SET
                mode = ?,
                config_version = config_version + 1,
                button_count = ?,
                page_count = ?,
                page_button_counts = ?,
                time_use_24h = ?,
                time_show_am_pm = ?
            WHERE id = ?
            """,
            (
                mode,
                page_counts[0] if page_counts else 6,
                page_count,
                page_counts_json,
                int(use_24h),
                int(show_am_pm),
                pad_internal_id,
            ),
        )

        # Disable existing buttons; new config will re-enable the active ones
        conn.execute(
            "UPDATE buttons SET enabled = 0 WHERE pad_id = ?",
            (pad_internal_id,),
        )

        # Precompute global slot offsets per page so we can map
        # (page, slot_on_page) -> unique global slot across the whole pad.
        offsets: list[int] = [0]
        for count in page_counts:
            offsets.append(offsets[-1] + count)

        # Update button configurations across all pages
        for btn in request.buttons:
            page = int(btn.get("page", 1) or 1)
            slot_on_page = btn.get("slot")
            if slot_on_page is None:
                continue

            if page < 1 or page > page_count:
                # Ignore out-of-range pages
                continue

            # Map page + per-page slot to a global slot index using offsets
            per_page_limit = page_counts[page - 1]
            local_slot = max(1, min(per_page_limit, int(slot_on_page)))
            slot = offsets[page - 1] + local_slot
            label = btn.get("label", "")
            icon = btn.get("icon", "")
            bg_color = btn.get("bg_color")
            icon_color = btn.get("icon_color")
            text_color = btn.get("text_color")
            show_text = btn.get("show_text")
            # For macro buttons, buttons.action_id should reference a row in
            # the macros table via a stable macro_action_id. For all other
            # buttons, we fall back to storing the high-level action_type
            # string as before.
            macro_action_id = btn.get("macro_action_id")
            if isinstance(macro_action_id, str) and macro_action_id:
                action = macro_action_id
            else:
                action = btn.get("action_type", "")

            # Optional application snapshot fields for "Launch Application" actions
            application_id = btn.get("application_id")
            application_name = btn.get("application_name")
            executable_path = btn.get("executable_path")
            working_directory = btn.get("working_directory")
            arguments = btn.get("arguments")
            override_arguments = btn.get("override_arguments")
            icon_path = btn.get("icon_path")
            run_mode = btn.get("run_mode")
            launch_source_snapshot_time = btn.get("launch_source_snapshot_time")
            source = btn.get("source")

            print(
                f"[API] save_pad_config page={page} slot_on_page={slot_on_page} "
                f"global_slot={slot} label={label!r} icon={icon!r} "
                f"bg_color={bg_color} icon_color={icon_color} text_color={text_color} show_text={show_text} action={action!r}",
                flush=True,
            )

            # Check if button exists
            cursor = conn.execute(
                "SELECT id FROM buttons WHERE pad_id = ? AND slot = ?",
                (pad_internal_id, slot)
            )
            existing = cursor.fetchone()

            show_text_val = int(bool(show_text)) if show_text is not None else 1

            if existing:
                # Update existing button
                conn.execute(
                    """
                    UPDATE buttons SET
                        label = ?,
                        icon_id = ?,
                        action_id = ?,
                        bg_color = ?,
                        icon_color = ?,
                        text_color = ?,
                        show_text = ?,
                        enabled = 1,
                        application_id = ?,
                        application_name = ?,
                        executable_path = ?,
                        working_directory = ?,
                        arguments = ?,
                        override_arguments = ?,
                        icon_path = ?,
                        run_mode = ?,
                        launch_source_snapshot_time = ?,
                        source = ?
                    WHERE pad_id = ? AND slot = ?
                    """,
                    (
                        label,
                        icon,
                        action,
                        bg_color,
                        icon_color,
                        text_color,
                        show_text_val,
                        application_id,
                        application_name,
                        executable_path,
                        working_directory,
                        arguments,
                        override_arguments,
                        icon_path,
                        run_mode,
                        launch_source_snapshot_time,
                        source,
                        pad_internal_id,
                        slot,
                    ),
                )
            else:
                # Insert new button
                conn.execute(
                    """
                    INSERT INTO buttons (
                        pad_id,
                        slot,
                        label,
                        icon_id,
                        action_id,
                        enabled,
                        bg_color,
                        icon_color,
                        text_color,
                        show_text,
                        application_id,
                        application_name,
                        executable_path,
                        working_directory,
                        arguments,
                        override_arguments,
                        icon_path,
                        run_mode,
                        launch_source_snapshot_time,
                        source
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, 1, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        pad_internal_id,
                        slot,
                        label,
                        icon,
                        action,
                        bg_color,
                        icon_color,
                        text_color,
                        show_text_val,
                        application_id,
                        application_name,
                        executable_path,
                        working_directory,
                        arguments,
                        override_arguments,
                        icon_path,
                        run_mode,
                        launch_source_snapshot_time,
                        source,
                    ),
                )

        # Mark that an updated configuration is available for this pad so
        # connected devices know to pull the new layout.
        conn.execute(
            "UPDATE pads SET update_pending = 1, update_required = 1 WHERE id = ?",
            (pad_internal_id,),
        )

        conn.commit()

    return {
        "success": True,
        "message": "Configuration saved successfully",
        "pad_id": pad_id,
        "mode": mode
    }


@router.get("/{pad_id}/logs/sessions", response_model=list[LogSessionResponse])
def list_pad_log_sessions(pad_id: str) -> list[LogSessionResponse]:
    """List recent log sessions (boots) for a pad, newest first."""

    config = get_config()
    with connect(config.database_path) as conn:
        cur = conn.execute(
            """
            SELECT id, session_uuid, started_at, ended_at, reboot_reason, fw_version
            FROM log_sessions
            WHERE pad_uuid = ?
            ORDER BY started_at DESC
            LIMIT 50
            """,
            (pad_id,),
        )
        rows = cur.fetchall()

    sessions: list[LogSessionResponse] = []
    for r in rows:
        sessions.append(
            LogSessionResponse(
                id=r["id"],
                session_uuid=r["session_uuid"],
                started_at=datetime.fromisoformat(r["started_at"]),
                ended_at=datetime.fromisoformat(r["ended_at"]) if r["ended_at"] else None,
                reboot_reason=r["reboot_reason"],
                fw_version=r["fw_version"],
            )
        )
    return sessions


@router.get("/{pad_id}/logs", response_model=list[LogEntryResponse])
def list_pad_logs(
    pad_id: str,
    session_uuid: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> list[LogEntryResponse]:
    """List log entries for a pad, optionally filtered by session_uuid."""

    config = get_config()
    params: list[object] = [pad_id]
    where = "pad_uuid = ?"

    if session_uuid:
        where += " AND session_id IN (SELECT id FROM log_sessions WHERE pad_uuid = ? AND session_uuid = ?)"
        params.extend([pad_id, session_uuid])

    params.extend([limit, offset])

    query = f"""
        SELECT id, session_id, seq, created_at, level, message
        FROM logs
        WHERE {where}
        ORDER BY created_at ASC, seq ASC
        LIMIT ? OFFSET ?
    """

    with connect(config.database_path) as conn:
        cur = conn.execute(query, tuple(params))
        rows = cur.fetchall()

    entries: list[LogEntryResponse] = []
    for r in rows:
        entries.append(
            LogEntryResponse(
                id=r["id"],
                session_id=r["session_id"],
                seq=r["seq"],
                created_at=datetime.fromisoformat(r["created_at"]),
                level=r["level"],
                message=r["message"],
            )
        )
    return entries


@router.post("/{pad_id}/pin/change")
def change_device_pin(
    pad_id: str,
    request: PINChangeRequest,
    x_pad_uuid: str = Header(...),
    x_device_token: str = Header(...),
) -> dict:
    """Change the device control panel PIN."""
    # Authenticate the request
    pad = _authenticate_pad_simple(x_pad_uuid, x_device_token)

    config = get_config()

    with connect(config.database_path) as conn:
        # Get current PIN hash
        cursor = conn.execute(
            "SELECT control_panel_pin_hash FROM pads WHERE id = ?",
            (pad["id"],)
        )
        row = cursor.fetchone()
        current_hash = row["control_panel_pin_hash"] if row else None

        # Verify current PIN
        if current_hash and current_hash != "":
            from displaypad_server.core.crypto import verify_secret
            if not verify_secret(request.current_pin, current_hash):
                raise HTTPException(status_code=401, detail="Current PIN is incorrect")

        # Validate new PIN length
        if len(request.new_pin) < 4 or len(request.new_pin) > 8:
            raise HTTPException(status_code=400, detail="PIN must be 4-8 digits")

        # Hash new PIN
        from displaypad_server.core.crypto import hash_secret
        new_pin_hash = hash_secret(request.new_pin)

        # Update PIN in database
        conn.execute(
            """
            UPDATE pads SET
                control_panel_pin_hash = ?,
                default_pin_active = 0
            WHERE id = ?
            """,
            (new_pin_hash, pad["id"])
        )
        conn.commit()

    return {
        "success": True,
        "message": "PIN changed successfully",
        "pin_length": len(request.new_pin)
    }
