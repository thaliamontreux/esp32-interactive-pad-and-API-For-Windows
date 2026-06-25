from fastapi import APIRouter, HTTPException

from displaypad_server.core.timezone_config import (
    get_timezone_config,
    set_timezone_name,
)


router = APIRouter()


# Curated list of common IANA timezone identifiers. This keeps the UI
# manageable while still covering typical regions. Additional zones can be
# added later without breaking existing clients.
COMMON_TIMEZONES: list[str] = [
    "America/Chicago",   # CDT (default)
    "America/New_York",
    "America/Denver",
    "America/Los_Angeles",
    "America/Phoenix",
    "America/Toronto",
    "America/Vancouver",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/Amsterdam",
    "Europe/Stockholm",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Singapore",
    "Australia/Sydney",
]


@router.get("/time/settings")
def get_time_settings() -> dict:
    """Return current timezone settings and the list of available zones."""

    cfg = get_timezone_config()
    return {
        "timezone": cfg.timezone_name,
        "available_timezones": COMMON_TIMEZONES,
    }


@router.put("/time/settings")
def update_time_settings(payload: dict) -> dict:
    """Update the global timezone used for pad time sync.

    Expects a JSON body like {"timezone": "America/Chicago"}.
    """

    tz = str(payload.get("timezone") or "").strip()
    if not tz:
        raise HTTPException(status_code=400, detail="Missing 'timezone' field")

    if tz not in COMMON_TIMEZONES:
        raise HTTPException(status_code=400, detail="Unsupported timezone identifier")

    cfg = set_timezone_name(tz)
    return {"timezone": cfg.timezone_name, "available_timezones": COMMON_TIMEZONES}
