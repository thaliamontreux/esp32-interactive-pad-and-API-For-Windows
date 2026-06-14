import re
import time
from datetime import datetime, timezone
from pathlib import Path

from displaypad_server.db.database import connect

PIN_RE = re.compile(r"^[0-9]{1,8}$")


def validate_pin(pin: str, *, require_exact_length: int | None = 8) -> bool:
    if not PIN_RE.fullmatch(pin):
        return False
    if require_exact_length is not None and len(pin) != require_exact_length:
        return False
    return True


def validate_timestamp(timestamp: int, *, max_skew_seconds: int = 60) -> bool:
    now = int(time.time())
    return abs(now - timestamp) <= max_skew_seconds


def redact_secret(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)


def check_and_store_nonce(
    pad_id: int, nonce: str, database_path: Path, max_age_seconds: int = 300
) -> bool:
    """Check if nonce was used and store it. Returns True if nonce is valid (not used)."""
    now = datetime.now(timezone.utc).isoformat()
    cutoff = datetime.now(timezone.utc).isoformat()

    with connect(database_path) as conn:
        # Check if nonce already exists
        cursor = conn.execute(
            "SELECT 1 FROM nonce_cache WHERE pad_id = ? AND nonce = ?",
            (pad_id, nonce),
        )
        if cursor.fetchone():
            return False  # Nonce already used - replay attack

        # Store nonce
        conn.execute(
            "INSERT INTO nonce_cache (pad_id, nonce, created_at) VALUES (?, ?, ?)",
            (pad_id, nonce, now),
        )
        conn.commit()
        return True


def cleanup_old_nonces(database_path: Path, max_age_seconds: int = 300) -> None:
    """Remove old nonces to prevent database growth."""
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)).isoformat()

    with connect(database_path) as conn:
        conn.execute("DELETE FROM nonce_cache WHERE created_at < ?", (cutoff,))
        conn.commit()
