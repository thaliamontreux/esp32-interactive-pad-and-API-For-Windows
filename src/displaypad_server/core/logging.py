"""Lightweight logging helpers with category-based filters.

This module centralizes debug logging so noisy subsystems (like the Task
Keypad monitor) can be selectively muted at runtime while critical and
error messages remain visible.
"""

from __future__ import annotations

from typing import Dict

# Simple category flags. These can be toggled at runtime by the GUI.
# Errors and critical issues should still be logged directly via print()
# or standard logging; these flags are intended for debug/verbose output.
_LOG_SETTINGS: Dict[str, bool] = {
    # High-frequency Task Keypad scanner and state messages
    "task_keypad": True,
}


def get_log_settings() -> Dict[str, bool]:
    """Return a copy of the current log category settings."""

    return dict(_LOG_SETTINGS)


def set_log_setting(category: str, enabled: bool) -> None:
    """Set a single category flag.

    Unknown categories are added so new categories can be introduced
    without code changes elsewhere.
    """

    _LOG_SETTINGS[category] = bool(enabled)


def update_log_settings(settings: Dict[str, bool]) -> None:
    """Bulk-update multiple category flags at once."""

    for key, value in settings.items():
        _LOG_SETTINGS[key] = bool(value)


def log_debug(category: str, message: str) -> None:
    """Log a debug/verbose message for *category* if enabled.

    This is intended for high-volume, non-critical messages. It writes
    directly to stdout using print() so it appears alongside existing
    console output.
    """

    if not _LOG_SETTINGS.get(category, True):
        return
    try:
        print(message, flush=True)
    except Exception:
        # Logging must never break application flow
        return
