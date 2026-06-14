import json
import secrets
from pathlib import Path
from pydantic import BaseModel

from displaypad_server.db.database import connect


class AppConfig(BaseModel):
    app_name: str = "DisplayPad Server"
    api_host: str = "0.0.0.0"
    api_port: int = 7443
    udp_discovery_port: int = 7442
    data_dir: Path = Path("data")
    database_path: Path = Path("data/displaypad.sqlite")
    default_control_panel_pin: str = "00000000"
    pairing_code_length: int = 6
    pairing_code_expire_seconds: int = 120
    pin_max_digits: int = 8
    pin_max_attempts: int = 5
    pin_lockout_seconds: int = 300


class APIIdentity(BaseModel):
    api_uuid: str
    api_secret: str


def _ensure_api_identity(database_path: Path) -> APIIdentity:
    """Generate or load API identity from database."""
    with connect(database_path) as conn:
        cursor = conn.execute("SELECT value FROM app_metadata WHERE key = ?", ("api_identity",))
        row = cursor.fetchone()

        if row:
            data = json.loads(row["value"])
            return APIIdentity(api_uuid=data["api_uuid"], api_secret=data["api_secret"])

        # Generate new identity
        api_uuid = f"api-{secrets.token_hex(8)}"
        api_secret = secrets.token_urlsafe(32)
        identity = APIIdentity(api_uuid=api_uuid, api_secret=api_secret)

        conn.execute(
            "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
            ("api_identity", json.dumps({"api_uuid": api_uuid, "api_secret": api_secret})),
        )
        conn.commit()

        return identity


def get_config() -> AppConfig:
    return AppConfig()


def get_api_identity(database_path: Path | None = None) -> APIIdentity:
    if database_path is None:
        database_path = get_config().database_path
    return _ensure_api_identity(database_path)
