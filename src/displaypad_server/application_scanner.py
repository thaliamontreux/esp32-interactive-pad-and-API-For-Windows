"""ApplicationScanner for Windows.

Scans Windows Start Menu / Taskbar shortcuts (``.lnk`` files) and stores
shortcut + executable metadata in the ``applications`` table.

IMPORTANT: This scanner never executes shortcuts or executables. It only
reads metadata via pywin32 (COM + version APIs).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class ScanStats:
    total_candidates: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "total_candidates": self.total_candidates,
            "added": self.added,
            "updated": self.updated,
            "skipped": self.skipped,
        }


_UNINSTALL_KEYWORDS = [
    "uninstall",
    "uninstaller",
    " remove ",
    " remove-",
    " remove_",
    " updater",
]


def _is_uninstaller(name: str, target: str, desc: str) -> bool:
    """Return True if this shortcut clearly looks like an uninstaller/updater.

    Uses simple keyword heuristics over the shortcut name, target path,
    and description. This is intentionally conservative.
    """

    text = " ".join([name, target, desc]).lower()
    for kw in _UNINSTALL_KEYWORDS:
        if kw in text:
            return True
    return False


def _expand(path: str) -> str:
    return os.path.expandvars(path or "")


def _read_lnk(shell, lnk_path: Path) -> Dict[str, object]:
    """Read basic shortcut metadata using WScript.Shell.

    Returns a dict with shortcut fields. Does not do any filtering.
    """

    shortcut = shell.CreateShortcut(str(lnk_path))

    target_raw = shortcut.Targetpath or ""
    arguments = shortcut.Arguments or ""

    target_expanded = _expand(target_raw)
    working_dir = _expand(shortcut.WorkingDirectory or "")

    # Some shortcuts may include arguments in Targetpath; try to separate
    # them safely if we see a space after .exe.
    target_path = target_expanded
    extra_args = ""
    lower = target_expanded.lower()
    exe_idx = lower.rfind(".exe")
    if exe_idx != -1 and exe_idx + 4 < len(lower):
        # There is content after .exe – treat it as additional arguments.
        exe_end = exe_idx + 4
        extra_args = target_expanded[exe_end:].strip()
        target_path = target_expanded[:exe_end].strip().strip('"')

    if extra_args:
        if arguments:
            arguments = f"{extra_args} {arguments}".strip()
        else:
            arguments = extra_args

    icon_location = shortcut.IconLocation or ""
    # IconLocation can be "path, index"; keep full string but strip env vars.
    icon_location = _expand(icon_location)

    return {
        "name": lnk_path.stem,
        "shortcut_path": str(lnk_path),
        "shortcut_folder": str(lnk_path.parent),
        "target_path": target_path,
        "arguments": arguments,
        "working_directory": working_dir,
        "icon_location": icon_location,
        "shortcut_description": shortcut.Description or "",
        "hotkey": shortcut.Hotkey or "",
        "window_style": shortcut.WindowStyle,
    }


def _get_exe_metadata(exe_path: str) -> Dict[str, object]:
    """Return extended file version metadata for a given .exe.

    If the file is missing or not an .exe, returns empty metadata.
    """

    from datetime import datetime

    try:
        import win32api  # type: ignore
    except Exception:
        # pywin32 not available; return empty metadata
        return {
            "exe_file_description": "",
            "exe_type": "",
            "exe_product_name": "",
            "exe_product_version": "",
            "exe_file_version": "",
            "exe_language": "",
            "exe_date_modified": "",
            "exe_original_filename": "",
            "exe_company_name": "",
            "exe_copyright": "",
            "exe_internal_name": "",
            "exe_legal_trademarks": "",
        }

    exe = Path(_expand(exe_path))

    empty = {
        "exe_file_description": "",
        "exe_type": "",
        "exe_product_name": "",
        "exe_product_version": "",
        "exe_file_version": "",
        "exe_language": "",
        "exe_date_modified": "",
        "exe_original_filename": "",
        "exe_company_name": "",
        "exe_copyright": "",
        "exe_internal_name": "",
        "exe_legal_trademarks": "",
    }

    if not exe.exists() or exe.suffix.lower() != ".exe":
        return empty

    try:
        info = win32api.GetFileVersionInfo(str(exe), "\\")
        translations = win32api.GetFileVersionInfo(
            str(exe), "\\VarFileInfo\\Translation"
        )
        if not translations:
            return empty

        lang, codepage = translations[0]
        string_base = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\"

        def read_value(name: str) -> str:
            try:
                return win32api.GetFileVersionInfo(str(exe), string_base + name)
            except Exception:
                return ""

        modified = datetime.fromtimestamp(exe.stat().st_mtime).isoformat(
            sep=" ", timespec="seconds"
        )

        return {
            "exe_file_description": read_value("FileDescription"),
            "exe_type": "Application",
            "exe_product_name": read_value("ProductName"),
            "exe_product_version": read_value("ProductVersion"),
            "exe_file_version": read_value("FileVersion"),
            "exe_language": f"{lang:04x}-{codepage:04x}",
            "exe_date_modified": modified,
            "exe_original_filename": read_value("OriginalFilename"),
            "exe_company_name": read_value("CompanyName"),
            "exe_copyright": read_value("LegalCopyright"),
            "exe_internal_name": read_value("InternalName"),
            "exe_legal_trademarks": read_value("LegalTrademarks"),
        }
    except Exception:
        return empty


def _scan_shortcut_root(root: Path, source: str, stats: ScanStats) -> None:
    """Scan a single shortcut root for .lnk files and upsert apps.

    ``source`` is stored in the applications table's detection_source field.
    """

    if not root.exists():
        return

    if sys.platform != "win32":
        print(f"[Scanner] Skipping {root} (not on Windows)", flush=True)
        return

    try:
        import win32com.client  # type: ignore
    except Exception:
        print("[Scanner] pywin32 not available; cannot scan shortcuts", flush=True)
        return

    from displaypad_server import applications as app_repo

    print(f"[Scanner] Scanning shortcuts under: {root} ({source})", flush=True)

    shell = win32com.client.Dispatch("WScript.Shell")

    for lnk_path in root.rglob("*.lnk"):
        lnk_path = lnk_path.resolve()
        try:
            data = _read_lnk(shell, lnk_path)
        except Exception as e:  # pragma: no cover - best-effort logging
            print(f"[Scanner] Failed to read shortcut {lnk_path}: {e}", flush=True)
            stats.skipped += 1
            continue

        name = str(data.get("name") or "").strip()
        target_path = str(data.get("target_path") or "").strip()
        desc = str(data.get("shortcut_description") or "")

        if not target_path:
            stats.skipped += 1
            continue

        if _is_uninstaller(name, target_path, desc):
            stats.skipped += 1
            continue

        exe_meta = _get_exe_metadata(target_path)

        # Build arguments and working dir
        working_dir = str(data.get("working_directory") or "")
        arguments = str(data.get("arguments") or "")

        # We only upsert into the current schema fields; richer metadata is
        # available in exe_meta but not yet mapped to dedicated columns.
        try:
            record = app_repo.upsert_scanned_application(
                name=name or Path(target_path).stem,
                executable_path=target_path,
                working_directory=working_dir or None,
                arguments=arguments or None,
                icon_path=str(data.get("icon_location") or "") or None,
                shortcut_path=str(data.get("shortcut_path") or ""),
                publisher=(exe_meta.get("exe_company_name") or None),
                version=(
                    exe_meta.get("exe_product_version")
                    or exe_meta.get("exe_file_version")
                    or None
                ),
                install_location=str(Path(target_path).parent),
                detection_source=source,
                enabled=True,
            )
        except Exception as e:  # pragma: no cover - best-effort logging
            print(f"[Scanner] Failed to upsert application for {lnk_path}: {e}", flush=True)
            stats.skipped += 1
            continue

        # If the repository returned a manual record for this executable,
        # treat it as skipped for scan statistics (we never modify manual
        # entries during scanning).
        if getattr(record, "is_manual", False):
            stats.skipped += 1
            continue

        stats.total_candidates += 1
        if record.last_scanned_at == record.created_at:
            stats.added += 1
        else:
            stats.updated += 1


def scan_installed_applications() -> Dict[str, int]:
    """Scan Start Menu / Taskbar shortcuts for installed applications.

    Returns a dictionary with simple statistics about the scan.
    """

    stats = ScanStats()

    print("[Scanner] Starting Start Menu / Taskbar shortcut scan", flush=True)

    # Current user Start Menu
    appdata = os.environ.get("APPDATA")
    if appdata:
        user_start = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        _scan_shortcut_root(user_start, "start_menu_user", stats)

        # Optional: Taskbar pinned shortcuts
        taskbar = (
            Path(appdata)
            / "Microsoft"
            / "Internet Explorer"
            / "Quick Launch"
            / "User Pinned"
            / "TaskBar"
        )
        _scan_shortcut_root(taskbar, "taskbar_pinned", stats)

    # All users Start Menu
    programdata = os.environ.get("PROGRAMDATA")
    if programdata:
        all_start = (
            Path(programdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
        )
        _scan_shortcut_root(all_start, "start_menu_all", stats)

    print(
        f"[Scanner] Completed: candidates={stats.total_candidates} "
        f"added={stats.added} updated={stats.updated} skipped={stats.skipped}",
        flush=True,
    )

    return stats.to_dict()
