"""Discovery API endpoints for DisplayPad Server."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import base64

from displaypad_server.core.discovery import discovery_service
from displaypad_server.core.config import get_config, get_api_identity
from displaypad_server.core.crypto import generate_secure_token, hash_secret
from displaypad_server.db.database import connect

router = APIRouter()


class DiscoveredPadResponse(BaseModel):
    uuid: str
    mac: str
    ip: str
    screen_width: int
    screen_height: int
    button_count: int
    discovered_at: str
    last_seen: str


class AssignPadRequest(BaseModel):
    uuid: str
    name: str
    mode: str = "macro_keypad"  # or "task_keypad"


class AssignPadResponse(BaseModel):
    success: bool
    pad_id: str
    message: str


class HelloRequest(BaseModel):
    uuid: str
    mac: str
    screen_width: int
    screen_height: int
    button_count: int


class HelloResponse(BaseModel):
    status: str
    message: str


@router.get("/pads", response_model=list[DiscoveredPadResponse])
def get_discovered_pads() -> list:
    """Get list of discovered (unassigned) pads broadcasting on the network."""
    discovered = discovery_service.get_discovered()
    return discovered


@router.post("/hello", response_model=HelloResponse)
def hello_from_pad(
    request: HelloRequest,
    http_request: Request
) -> HelloResponse:
    """Receive hello from a pad that found us via network scan."""
    # Get client IP from request
    client_ip = http_request.client.host if http_request.client else "unknown"

    # Add to discovered list
    discovery_service.add_discovered_pad(
        uuid=request.uuid,
        mac=request.mac,
        ip=client_ip,
        width=request.screen_width,
        height=request.screen_height,
        buttons=request.button_count
    )

    print(f"[Discovery] Hello from pad {request.uuid[:16]}... at {client_ip}")

    return HelloResponse(
        status="ok",
        message="Pad discovered. Waiting for user to add you in the GUI."
    )


@router.post("/assign", response_model=AssignPadResponse)
def assign_pad(
    request: AssignPadRequest,
    http_request: Request
) -> AssignPadResponse:
    """Assign a discovered pad - auto-accepts any device."""
    config = get_config()
    identity = get_api_identity(config.database_path)

    # Get actual client IP
    client_ip = http_request.client.host if http_request.client else "unknown"
    print(f"[Auto-Assign] Device {request.uuid[:16]}... from {client_ip}")

    # Auto-create pad info (accept any device)
    pad_info = {
        "uuid": request.uuid,
        "mac": request.uuid,
        "ip": client_ip,
        "screen_width": 320,
        "screen_height": 240,
        "button_count": 6
    }

    # Generate device token
    device_token = generate_secure_token(32)

    # Get or create pad ID
    with connect(config.database_path) as conn:
        # Check if pad already exists
        cursor = conn.execute(
            "SELECT id, encrypted_token FROM pads WHERE pad_uuid = ?",
            (request.uuid,)
        )
        existing = cursor.fetchone()

        if existing:
            # Update existing
            import base64
            encryption_key = identity.api_secret[:32].encode()
            encrypted_token = bytes([b ^ encryption_key[i % len(encryption_key)]
                                   for i, b in enumerate(device_token.encode())])
            encrypted_token_b64 = base64.b64encode(encrypted_token).decode()

            conn.execute(
                """UPDATE pads SET
                    encrypted_token = ?,
                    token_hash = ?,
                    mode = ?,
                    name = ?,
                    enabled = 1,
                    last_ip = ?
                WHERE pad_uuid = ?""",
                (encrypted_token_b64, hash_secret(device_token)[:32],
                 request.mode, request.name, client_ip, request.uuid)
            )
            # Use the external pad UUID string for API responses
            pad_id = request.uuid
        else:
            # Create new pad
            import base64
            from datetime import datetime, timezone

            encryption_key = identity.api_secret[:32].encode()
            encrypted_token = bytes(
                [b ^ encryption_key[i % len(encryption_key)] for i, b in enumerate(device_token.encode())]
            )
            encrypted_token_b64 = base64.b64encode(encrypted_token).decode()

            default_pin_hash = hash_secret(config.default_control_panel_pin)
            now = datetime.now(timezone.utc).isoformat()

            # NOTE: pads.screen_driver is NOT NULL, so we must provide a
            # value here. For now we assume the default ILI9341 driver,
            # matching the ESP32 firmware config. We also persist last_ip
            # so the server remembers where the pad was first seen.
            cursor = conn.execute(
                """INSERT INTO pads (
                    pad_uuid, name, mode, screen_width, screen_height,
                    screen_driver,
                    button_count, token_hash, encrypted_token, paired_at,
                    enabled, config_version, control_panel_pin_hash, default_pin_active, last_ip
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, 1, ?)""",
                (
                    request.uuid,
                    request.name,
                    request.mode,
                    pad_info["screen_width"],
                    pad_info["screen_height"],
                    "ILI9341",
                    pad_info["button_count"],
                    hash_secret(device_token)[:32],
                    encrypted_token_b64,
                    now,
                    default_pin_hash,
                    client_ip,
                ),
            )
            conn.commit()
            # New pads also use the provided UUID as their external ID
            pad_id = request.uuid

        conn.commit()

    # Send assignment to pad via UDP
    success = discovery_service.assign_pad(
        request.uuid, device_token, identity.api_uuid, config.api_port
    )

    if success:
        return AssignPadResponse(
            success=True,
            pad_id=pad_id,
            message=f"Pad assigned successfully. Device token sent to {pad_info['ip']}"
        )
    else:
        return AssignPadResponse(
            success=False,
            pad_id=pad_id,
            message="Pad created but failed to send assignment packet"
        )
