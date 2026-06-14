"""Windows foreground-window helpers.

These utilities are used to bring an existing application's main window to
the front when a keypad button is pressed for an app that is already
running.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


def _enum_windows_for_pid(target_pid: int) -> list[int]:
    """Return a list of top-level window handles (HWND) owned by pid.

    We only keep visible windows; this avoids background/helper windows.
    """

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    EnumWindows = user32.EnumWindows
    EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
    EnumWindows.restype = wintypes.BOOL

    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    GetWindowThreadProcessId.restype = wintypes.DWORD

    IsWindowVisible = user32.IsWindowVisible
    IsWindowVisible.argtypes = [wintypes.HWND]
    IsWindowVisible.restype = wintypes.BOOL

    hwnds: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd: int, lparam: int) -> bool:  # type: ignore[override]
        try:
            if not IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD(0)
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) == int(target_pid):
                hwnds.append(hwnd)
        except Exception:
            # Ignore any errors and continue enumeration.
            return True
        return True

    # Enumerate all top-level windows
    EnumWindows(_callback, 0)
    return hwnds


def bring_window_to_front(pid: int) -> bool:
    """Best-effort attempt to bring any window for *pid* to the foreground.

    Returns True if a window was found and we requested activation; False
    otherwise. Failures are intentionally swallowed so that a failed focus
    attempt does not break the rest of the server.
    """

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        SetForegroundWindow = user32.SetForegroundWindow
        SetForegroundWindow.argtypes = [wintypes.HWND]
        SetForegroundWindow.restype = wintypes.BOOL

        ShowWindow = user32.ShowWindow
        ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        ShowWindow.restype = wintypes.BOOL

        IsIconic = user32.IsIconic
        IsIconic.argtypes = [wintypes.HWND]
        IsIconic.restype = wintypes.BOOL

        SW_RESTORE = 9

        hwnds = _enum_windows_for_pid(pid)
        if not hwnds:
            return False

        # Prefer the first window; in practice this is usually the main one.
        hwnd = hwnds[0]

        # If minimized, restore before bringing to foreground.
        if IsIconic(hwnd):
            ShowWindow(hwnd, SW_RESTORE)

        SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False
