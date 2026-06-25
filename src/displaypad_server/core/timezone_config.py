import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from displaypad_server.db.database import connect
from displaypad_server.core.config import get_config


_METADATA_KEY = "timezone_config"
_DEFAULT_TZ = "America/Chicago"  # CDT by default


@dataclass
class TimezoneConfig:
    """Global timezone configuration for DisplayPad Server.

    timezone_name stores an IANA timezone identifier such as
    "America/Chicago". The default is CDT until changed by the user.
    """

    timezone_name: str = _DEFAULT_TZ


def _load_raw(database_path: Path) -> dict | None:
    with connect(database_path) as conn:
        cur = conn.execute(
            "SELECT value FROM app_metadata WHERE key = ?", (_METADATA_KEY,)
        )
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value"])
        except Exception:
            return None


def _save_raw(database_path: Path, data: dict) -> None:
    payload = json.dumps(data)
    with connect(database_path) as conn:
        cur = conn.execute(
            "SELECT value FROM app_metadata WHERE key = ?", (_METADATA_KEY,)
        )
        row = cur.fetchone()
        if row:
            conn.execute(
                "UPDATE app_metadata SET value = ? WHERE key = ?",
                (payload, _METADATA_KEY),
            )
        else:
            conn.execute(
                "INSERT INTO app_metadata (key, value) VALUES (?, ?)",
                (_METADATA_KEY, payload),
            )
        conn.commit()


def get_timezone_config() -> TimezoneConfig:
    """Return current timezone configuration (defaulting to CDT).

    On first use, this will create an entry in app_metadata so that the
    selection persists across restarts.
    """

    cfg = get_config()
    raw = _load_raw(cfg.database_path)
    if not raw or "timezone_name" not in raw:
        tz = TimezoneConfig()
        _save_raw(cfg.database_path, {"timezone_name": tz.timezone_name})
        return tz

    tz_name = str(raw.get("timezone_name") or _DEFAULT_TZ)
    return TimezoneConfig(timezone_name=tz_name)


def set_timezone_name(timezone_name: str) -> TimezoneConfig:
    """Persist a new timezone name and return the resulting config."""

    cfg = get_config()
    if not timezone_name:
        timezone_name = _DEFAULT_TZ

    # Basic validation: ensure the identifier is recognized by zoneinfo.
    try:
        ZoneInfo(timezone_name)
    except Exception:
        # Fall back to default CDT if invalid.
        timezone_name = _DEFAULT_TZ

    _save_raw(cfg.database_path, {"timezone_name": timezone_name})
    return TimezoneConfig(timezone_name=timezone_name)


def get_current_offset_minutes() -> int:
    """Return the current UTC offset in minutes for the configured timezone."""

    tz_cfg = get_timezone_config()
    try:
        tz = ZoneInfo(tz_cfg.timezone_name)
    except Exception:
        tz = ZoneInfo(_DEFAULT_TZ)

    now = datetime.now(tz)
    offset = now.utcoffset() or timedelta(0)
    return int(offset.total_seconds() // 60)


def get_local_epoch() -> int:
    """Return an epoch value that encodes the host's local wall-clock time.

    The returned integer is derived from the configured timezone's local
    datetime so that when devices treat this epoch as a simple wall-clock
    without additional timezone adjustments, the displayed time matches the
    server host.
    """

    tz_cfg = get_timezone_config()
    try:
        tz = ZoneInfo(tz_cfg.timezone_name)
    except Exception:
        tz = ZoneInfo(_DEFAULT_TZ)

    # We want an epoch value such that when the ESP32 calls gmtime(epoch),
    # the resulting hour/minute match the host's local wall-clock time in the
    # configured timezone. For an aware datetime, .timestamp() returns the
    # underlying UTC-based POSIX seconds. To "bake in" the local offset so
    # that gmtime(epoch) yields local time, we add the current UTC offset.
    now_local = datetime.now(tz)
    offset = now_local.utcoffset() or timedelta(0)
    timestamp_utc = now_local.timestamp()
    epoch_for_device = timestamp_utc + offset.total_seconds()
    return int(epoch_for_device)
