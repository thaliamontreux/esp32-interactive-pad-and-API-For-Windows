from fastapi import APIRouter

from displaypad_server.core import logging as dp_logging

router = APIRouter()


@router.get("/logging/settings")
def get_logging_settings() -> dict[str, bool]:
    """Return current debug/info logging category settings.

    This controls high-volume informational logs (task keypad, BLE bridge,
    wifi, app, etc.). Critical errors are not affected and are still printed
    directly.
    """

    return dp_logging.get_log_settings()


@router.put("/logging/settings")
def update_logging_settings(settings: dict[str, bool]) -> dict[str, bool]:
    """Update one or more logging categories.

    Unknown categories are added automatically. The response returns the full
    current settings after the update.
    """

    dp_logging.update_log_settings(settings)
    return dp_logging.get_log_settings()
