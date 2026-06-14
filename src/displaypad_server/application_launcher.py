"""Safe application launching utilities for DisplayPad on Windows.

The ESP32 device never sees Windows paths. It only sends button/slot
press events. The Windows host reads the pre-snapshotted application
fields from the database and uses this module to start processes in a
safe way.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import ctypes


@dataclass
class LaunchSpec:
    executable_path: str
    working_directory: Optional[str] = None
    arguments: Optional[str] = None
    run_mode: str = "normal"  # future: "normal", "elevated", etc.


def _split_arguments(arg_string: str) -> list[str]:
    """Very conservative argument splitter.

    We avoid invoking a shell. The user-provided string is split on
    whitespace while keeping quoted segments together.
    """

    import shlex

    if not arg_string:
        return []
    return shlex.split(arg_string, posix=False)


def _launch_with_shell(exe: Path, args_str: str, cwd: Optional[str]) -> bool:
    """Launch using ShellExecuteW with SW_RESTORE so the app comes to the front.

    Returns True on success, False if ShellExecuteW reports an error.
    """

    # ShellExecuteW(HWND hwnd, LPCWSTR lpOperation, LPCWSTR lpFile,
    #               LPCWSTR lpParameters, LPCWSTR lpDirectory, INT nShowCmd)
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ShellExecuteW = shell32.ShellExecuteW
        ShellExecuteW.restype = ctypes.c_void_p
        ShellExecuteW.argtypes = [
            ctypes.c_void_p,  # hwnd
            ctypes.c_wchar_p,  # lpOperation
            ctypes.c_wchar_p,  # lpFile
            ctypes.c_wchar_p,  # lpParameters
            ctypes.c_wchar_p,  # lpDirectory
            ctypes.c_int,  # nShowCmd
        ]

        # SW_RESTORE (9) activates and displays a window. If the window is
        # minimized or maximized, Windows restores it to its normal size and
        # position, which is the behavior we want when a keypad button starts
        # or re-activates an application.
        SW_RESTORE = 9
        hwnd = None
        operation = "open"
        file_path = str(exe)
        parameters = args_str or None
        directory = cwd or None

        result = ShellExecuteW(hwnd, operation, file_path, parameters, directory, SW_RESTORE)
        # Per MSDN, values > 32 indicate success.
        if isinstance(result, int):
            success = result > 32
        else:
            # On 64-bit, result may be a pointer-sized value; treat non-zero as success.
            success = bool(result) and int(ctypes.cast(result, ctypes.c_size_t).value or 0) > 32

        if not success:
            err = ctypes.get_last_error()
            try:
                print(f"[LAUNCH] ShellExecuteW failed file={file_path!r} err={err}", flush=True)
            except Exception:
                pass
        return success
    except Exception as e:
        try:
            print(f"[LAUNCH] ShellExecuteW exception for {exe!r}: {e}", flush=True)
        except Exception:
            pass
        return False


def launch_application(spec: LaunchSpec) -> bool:
    """Launch an application safely on Windows and bring it to the foreground.

    Preferred path is ShellExecuteW with SW_SHOWNORMAL, which both starts
    the application and requests that its window be shown/activated in the
    foreground. If that fails, we fall back to subprocess.Popen.
    """

    if not spec.executable_path:
        return False

    exe = Path(spec.executable_path)

    # Basic safety: executable must exist and be a file
    if not exe.exists() or not exe.is_file():
        return False

    # Determine working directory
    if spec.working_directory:
        cwd: Optional[str] = spec.working_directory
    else:
        cwd = str(exe.parent)

    # Build argument string for ShellExecuteW and Popen
    args_str = spec.arguments or ""

    # First attempt: ShellExecuteW with SW_SHOWNORMAL to bring to foreground.
    if sys.platform.startswith("win"):
        if _launch_with_shell(exe, args_str, cwd):
            return True

    # Fallback: subprocess.Popen (still starts the app, but may not steal focus)
    args: list[str] = [str(exe)]
    args.extend(_split_arguments(args_str))

    env = os.environ.copy()

    try:
        subprocess.Popen(args, cwd=cwd, env=env, shell=False)
    except Exception as e:
        try:
            print(f"[LAUNCH] subprocess.Popen failed for {exe!r}: {e}", flush=True)
        except Exception:
            pass
        return False

    return True
