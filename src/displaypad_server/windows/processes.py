"""Lightweight helpers for inspecting running Windows processes.

These utilities are used by the DisplayPad Server GUI to track which
applications from the Application Library are actually running, so that
"common apps" can be inferred over time.
"""

from __future__ import annotations

from pathlib import Path
from typing import List


def list_running_executables() -> List[str]:
    """Return absolute executable paths for currently running processes.

    This uses psutil when available. If psutil is not installed or
    fails, an empty list is returned so callers can fail gracefully
    without impacting the rest of the GUI.
    """

    try:
        import psutil  # type: ignore[import-not-found]
    except Exception:
        return []

    paths: list[str] = []
    try:
        for proc in psutil.process_iter(["exe"]):
            try:
                exe = proc.info.get("exe")  # type: ignore[union-attr]
                if not exe:
                    continue
                # Normalise path to an absolute, resolved form
                try:
                    resolved = str(Path(exe).resolve())
                except Exception:
                    resolved = str(exe)
                paths.append(resolved)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception:
        # Any unexpected failure should not break the GUI; just return what
        # we have (or an empty list).
        return []

    return paths
