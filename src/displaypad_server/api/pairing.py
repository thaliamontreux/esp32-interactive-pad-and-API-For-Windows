"""Pairing endpoints for ESP32 DisplayPads."""

from datetime import datetime, timezone, timedelta
from typing import Literal
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from displaypad_server.core.config import get_config, get_api_identity
from displaypad_server.core.crypto import generate_pairing_code, hash_secret, generate_secure_token
from displaypad_server.db.database import connect, initialize_database

router = APIRouter()

# Track active pairing session (auto-rotates every 300 seconds)
_active_pairing_code: str | None = None
_active_pairing_code_hash: str | None = None
_active_pairing_expires: datetime | None = None
_auto_rotation_enabled: bool = True
_auto_rotation_interval: int = 300  # 5 minutes = 300 seconds
_rotation_timer: threading.Timer | None = None


def _generate_new_pairing_code():
    """Generate a new pairing code."""
    global _active_pairing_code, _active_pairing_code_hash, _active_pairing_expires

    config = get_config()

    # Generate new pairing code
    _active_pairing_code = generate_pairing_code(config.pairing_code_length)
    _active_pairing_code_hash = hash_secret(_active_pairing_code)
    _active_pairing_expires = datetime.now(timezone.utc) + timedelta(
        seconds=config.pairing_code_expire_seconds
    )

    print(f"[Pairing] Auto-generated new pairing code: {_active_pairing_code}")


def _rotation_worker():
    """Background worker that rotates the pairing code every 300 seconds."""
    global _rotation_timer

    while _auto_rotation_enabled:
        _generate_new_pairing_code()

        # Schedule next rotation
        time.sleep(_auto_rotation_interval)


def start_auto_rotation():
    """Start the auto-rotation of pairing codes."""
    global _auto_rotation_enabled, _rotation_timer

    _auto_rotation_enabled = True

    # Generate initial code
    _generate_new_pairing_code()

    # Start background thread
    rotation_thread = threading.Thread(target=_rotation_worker, daemon=True)
    rotation_thread.start()

    print("[Pairing] Auto-rotation started (300s interval)")


def stop_auto_rotation():
    """Stop the auto-rotation of pairing codes."""
    global _auto_rotation_enabled
    _auto_rotation_enabled = False
    print("[Pairing] Auto-rotation stopped")


class ScreenInfo(BaseModel):
    width: int
    height: int
    driver: str
    touch: bool = True


class PairingHelloRequest(BaseModel):
    pad_uuid: str
    screen: ScreenInfo
    firmware: str


class PairingHelloResponse(BaseModel):
    pairing_allowed: bool
    api_name: str
    api_uuid: str
    api_ip: str
    api_port: int
    code_required: bool
    expires_in: int


class PairingCompleteRequest(BaseModel):
    pad_uuid: str
    pairing_code: str
    screen: ScreenInfo
    firmware: str


class ControlPanelPINPolicy(BaseModel):
    enabled: bool
    pin_length: int
    pin_hash: str
    default_pin_active: bool
    max_attempts: int
    lockout_seconds: int


class PairingCompleteResponse(BaseModel):
    paired: bool
    pad_id: str
    device_token: str
    api_uuid: str
    api_host: str
    api_ip_backup: str
    api_port: int
    api_fingerprint: str
    control_panel_pin: ControlPanelPINPolicy


def _get_local_ip() -> str:
    """Get local IP address for API."""
    import socket
    try:
        # Connect to a public address to determine local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(('10.254.254.254', 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def _get_hostname() -> str:
    """Get hostname for API."""
    import socket
    return socket.gethostname()


@router.post("/hello", response_model=PairingHelloResponse)
def pairing_hello(request: PairingHelloRequest, http_request: Request) -> PairingHelloResponse:
    """Handle pairing hello from ESP32. Returns API info if pairing is allowed."""
    global _active_pairing_code, _active_pairing_code_hash, _active_pairing_expires

    config = get_config()
    identity = get_api_identity(config.database_path)

    # Check if there's an active pairing session
    pairing_allowed = _active_pairing_code is not None and _active_pairing_expires is not None
    if pairing_allowed and datetime.now(timezone.utc) > _active_pairing_expires:
        pairing_allowed = False
        _active_pairing_code = None
        _active_pairing_code_hash = None
        _active_pairing_expires = None

    # Get client IP
    client_host = http_request.client.host if http_request.client else _get_local_ip()

    return PairingHelloResponse(
        pairing_allowed=pairing_allowed,
        api_name=_get_hostname(),
        api_uuid=identity.api_uuid,
        api_ip=_get_local_ip(),
        api_port=config.api_port,
        code_required=True,
        expires_in=config.pairing_code_expire_seconds if pairing_allowed else 0,
    )


@router.post("/complete", response_model=PairingCompleteResponse)
def pairing_complete(request: PairingCompleteRequest) -> PairingCompleteResponse:
    """Complete pairing process with code validation."""
    global _active_pairing_code, _active_pairing_code_hash, _active_pairing_expires

    config = get_config()
    identity = get_api_identity(config.database_path)

    # Validate pairing session exists and hasn't expired
    if _active_pairing_code is None or _active_pairing_expires is None:
        raise HTTPException(status_code=400, detail="No active pairing session")

    if datetime.now(timezone.utc) > _active_pairing_expires:
        _active_pairing_code = None
        _active_pairing_code_hash = None
        _active_pairing_expires = None
        raise HTTPException(status_code=400, detail="Pairing session expired")

    # Validate pairing code
    from displaypad_server.core.crypto import verify_secret
    if not verify_secret(request.pairing_code, _active_pairing_code_hash):
        raise HTTPException(status_code=400, detail="Invalid pairing code")

    # Mark session as used
    _active_pairing_code = None
    _active_pairing_code_hash = None
    _active_pairing_expires = None

    # Initialize database if needed
    initialize_database(config.database_path)

    # Generate device token
    device_token = generate_secure_token(32)
    print(f"[Pairing] Generated device_token (first 8): {device_token[:8]}...", flush=True)

    # Store both hash (for verification) and encrypted token (for HMAC)
    token_hash = hash_secret(device_token)

    # For HMAC verification, we need the raw token - store it "encrypted" (simple XOR for now)
    import base64
    encryption_key = identity.api_secret[:32].encode()
    encrypted_token = bytes([b ^ encryption_key[i % len(encryption_key)] for i, b in enumerate(device_token.encode())])
    encrypted_token_b64 = base64.b64encode(encrypted_token).decode()
    print(f"[Pairing] encrypted_token_b64 (first 16): {encrypted_token_b64[:16]}...", flush=True)

    # Test decryption to verify
    test_decrypted = bytes([b ^ encryption_key[i % len(encryption_key)] for i, b in enumerate(base64.b64decode(encrypted_token_b64))]).decode()
    print(f"[Pairing] Test decryption (first 8): {test_decrypted[:8]}... Match: {test_decrypted == device_token}", flush=True)

    # Hash default PIN
    default_pin_hash = hash_secret(config.default_control_panel_pin)

    # Create or update pad record
    pad_id = f"pad-{request.pad_uuid.replace('pad-', '')[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    with connect(config.database_path) as conn:
        # Check if pad already exists
        cursor = conn.execute(
            "SELECT id FROM pads WHERE pad_uuid = ?",
            (request.pad_uuid,)
        )
        existing = cursor.fetchone()

        if existing:
            # Update existing pad
            conn.execute(
                """
                UPDATE pads SET
                    token_hash = ?,
                    encrypted_token = ?,
                    paired_at = ?,
                    last_seen = ?,
                    enabled = 1,
                    revoked = 0,
                    screen_width = ?,
                    screen_height = ?,
                    screen_driver = ?,
                    control_panel_pin_hash = ?,
                    default_pin_active = 1
                WHERE pad_uuid = ?
                """,
                (
                    token_hash, encrypted_token_b64, now, now,
                    request.screen.width, request.screen.height, request.screen.driver,
                    default_pin_hash, request.pad_uuid
                )
            )
        else:
            # Insert new pad
            conn.execute(
                """
                INSERT INTO pads (
                    pad_uuid, name, mode, screen_width, screen_height, screen_driver,
                    button_count, token_hash, encrypted_token, paired_at, last_seen, enabled, revoked,
                    config_version, control_panel_pin_hash, default_pin_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.pad_uuid, pad_id, 'button_pad',
                    request.screen.width, request.screen.height, request.screen.driver,
                    6, token_hash, encrypted_token_b64, now, now, 1, 0, 1, default_pin_hash, 1
                )
            )

        conn.commit()

    print(f"[Pairing] Returning device_token to pad (first 8): {device_token[:8]}...", flush=True)

    return PairingCompleteResponse(
        paired=True,
        pad_id=pad_id,
        device_token=device_token,
        api_uuid=identity.api_uuid,
        api_host=_get_hostname(),
        api_ip_backup=_get_local_ip(),
        api_port=config.api_port,
        api_fingerprint="SHA256_PLACEHOLDER",  # Would be actual cert fingerprint
        control_panel_pin=ControlPanelPINPolicy(
            enabled=True,
            pin_length=config.pin_max_digits,
            pin_hash=default_pin_hash,
            default_pin_active=True,
            max_attempts=config.pin_max_attempts,
            lockout_seconds=config.pin_lockout_seconds,
        ),
    )


# Tray app endpoint to start pairing
@router.post("/start")
def start_pairing() -> dict:
    """Start a new pairing session from the tray app."""
    global _active_pairing_code, _active_pairing_code_hash, _active_pairing_expires

    config = get_config()

    # Generate new pairing code
    _active_pairing_code = generate_pairing_code(config.pairing_code_length)
    _active_pairing_code_hash = hash_secret(_active_pairing_code)
    _active_pairing_expires = datetime.now(timezone.utc) + timedelta(
        seconds=config.pairing_code_expire_seconds
    )

    return {
        "pairing_code": _active_pairing_code,
        "expires_in": config.pairing_code_expire_seconds,
        "started": True,
    }


@router.post("/cancel")
def cancel_pairing() -> dict:
    """Cancel active pairing session."""
    global _active_pairing_code, _active_pairing_code_hash, _active_pairing_expires

    _active_pairing_code = None
    _active_pairing_code_hash = None
    _active_pairing_expires = None

    return {"cancelled": True}


@router.get("/current")
def get_current_pairing_code() -> dict:
    """Get the current pairing code and time remaining."""
    global _active_pairing_code, _active_pairing_expires, _auto_rotation_enabled

    if _active_pairing_code is None or _active_pairing_expires is None:
        return {
            "has_code": False,
            "pairing_code": None,
            "expires_in": 0,
            "auto_rotation": _auto_rotation_enabled,
            "rotation_interval": _auto_rotation_interval
        }

    now = datetime.now(timezone.utc)
    expires_in = max(0, int((_active_pairing_expires - now).total_seconds()))

    return {
        "has_code": True,
        "pairing_code": _active_pairing_code,
        "expires_in": expires_in,
        "auto_rotation": _auto_rotation_enabled,
        "rotation_interval": _auto_rotation_interval
    }


@router.post("/rotate-now")
def rotate_pairing_code_now() -> dict:
    """Manually rotate the pairing code immediately."""
    _generate_new_pairing_code()
    return {
        "rotated": True,
        "pairing_code": _active_pairing_code,
        "expires_in": 300
    }


@router.post("/auto-rotation/{enabled}")
def toggle_auto_rotation(enabled: bool) -> dict:
    """Enable or disable auto-rotation of pairing codes."""
    global _auto_rotation_enabled

    _auto_rotation_enabled = enabled

    if enabled:
        # Restart rotation if needed
        start_auto_rotation()

    return {
        "auto_rotation": _auto_rotation_enabled,
        "rotation_interval": _auto_rotation_interval
    }
