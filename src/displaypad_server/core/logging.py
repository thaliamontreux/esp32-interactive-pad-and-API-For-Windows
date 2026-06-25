"""Lightweight logging helpers with category-based filters.

This module centralizes debug logging so noisy subsystems (like the Task
Keypad monitor) can be selectively muted at runtime while critical and
error messages remain visible.
"""

from __future__ import annotations

from typing import Dict
from pathlib import Path
import json

from displaypad_server.core.config import get_config

# Simple category flags. These can be toggled at runtime by the GUI.
# Errors and critical issues should still be logged directly via print()
# or standard logging; these flags are intended for debug/verbose output.
_LOG_SETTINGS: Dict[str, bool] = {
    # High-frequency Taskpad (Task Keypad) scanner and state messages
    "taskpad": True,
    # BLE bridge informational chatter (connection attempts, acks, etc.)
    "ble_bridge": True,
    # Placeholder categories for future network-related logs
    "wifi": True,
    # General high-level application info/debug messages
    "app": True,
    # HTTP API request/response info (FastAPI/uvicorn-level chatter)
    "api": True,
    # Power / security related events (host lock/unlock, backlight changes)
    "power": True,
}


def _settings_path() -> Path:
    """Return path to the persisted logging settings file.

    Falls back to ./data if the configured data_dir is unavailable.
    """

    try:
        cfg = get_config()
        base = Path(cfg.data_dir)
    except Exception:
        base = Path("data")
    return base / "logging_settings.json"


def _load_persisted_settings() -> None:
    """Load persisted settings from disk into _LOG_SETTINGS if available."""

    path = _settings_path()
    try:
        if not path.is_file():
            return
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            _LOG_SETTINGS[str(key)] = bool(value)
    except Exception:
        # Never fail app startup due to logging persistence issues
        return


def _persist_settings() -> None:
    """Persist current _LOG_SETTINGS to disk (best-effort)."""

    path = _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(_LOG_SETTINGS, f, sort_keys=True)
    except Exception:
        # Logging persistence must not break application flow
        return


_load_persisted_settings()


def get_log_settings() -> Dict[str, bool]:
    """Return a copy of the current log category settings."""

    return dict(_LOG_SETTINGS)


def set_log_setting(category: str, enabled: bool) -> None:
    """Set a single category flag.

    Unknown categories are added so new categories can be introduced
    without code changes elsewhere.
    """
    _LOG_SETTINGS[category] = bool(enabled)
    _persist_settings()


def update_log_settings(settings: Dict[str, bool]) -> None:
    """Bulk-update multiple category flags at once."""

    for key, value in settings.items():
        _LOG_SETTINGS[key] = bool(value)
    _persist_settings()


def log_debug(category: str, message: str) -> None:
    """Log a debug/verbose message for *category* if enabled.

    This is intended for high-volume, non-critical messages. It writes
    directly to stdout using print() so it appears alongside existing
    console output.
    """

    if not _LOG_SETTINGS.get(category, True):
        return
    try:
        # Highlight power/security-related messages in red so they stand out
        # in the console. Other categories use the default color.
        if category == "power":
            print(f"\033[31m{message}\033[0m", flush=True)
        else:
            print(message, flush=True)
    except Exception:
        # Logging must never break application flow
        return
