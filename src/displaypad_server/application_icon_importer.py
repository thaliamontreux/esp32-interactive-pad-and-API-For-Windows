from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from displaypad_server.core.config import get_config
from displaypad_server import applications as app_repo
from displaypad_server import application_icons as app_icon_repo
from displaypad_server.windows.icons import extract_icon_to_png


@dataclass
class ImportStats:
    total_apps: int = 0
    icons_created: int = 0
    icons_updated: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, int]:
        return {
            "total_apps": self.total_apps,
            "icons_created": self.icons_created,
            "icons_updated": self.icons_updated,
            "skipped": self.skipped,
            "errors": self.errors,
            # error_details is a list of human-readable strings describing
            # which applications failed and why.
            "error_details": self.error_details,
        }


def import_program_icons() -> Dict[str, int]:
    """Import PNG icons for applications discovered by the scanner.

    This uses only the executable paths already present in the applications
    table. It does not recursively scan Program Files or modify the existing
    monochrome icon pipeline.
    """

    config = get_config()
    # Store icons as regular PNG files under a top-level ./application-icons
    # directory next to the data directory. For example, if data_dir is
    # f:/keypad-api/data then icons are written to f:/keypad-api/application-icons.
    # The database stores only a relative path like "application-icons/chrome.png".
    project_root = Path(config.data_dir).parent
    icons_dir = project_root / "application-icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    stats = ImportStats()

    apps = app_repo.list_applications(enabled_only=True, search=None)
    stats.total_apps = len(apps)

    for app in apps:
        exe_path = app.executable_path
        if not exe_path:
            stats.skipped += 1
            stats.errors += 1
            stats.error_details.append(f"{app.name or '(unnamed application)'}: missing executable path")
            continue

        exe = Path(exe_path)
        if not exe.exists():
            stats.skipped += 1
            stats.errors += 1
            stats.error_details.append(f"{app.name or exe_path}: executable not found")
            continue

        # Derive a stable, filesystem-safe filename from the executable name.
        # Example: "C:/Program Files/Foo/bar.exe" -> "bar.png".
        exe_stem = exe.stem or f"app_{app.id}"
        # Very basic sanitization: replace path separators and spaces.
        safe_stem = exe_stem.replace("/", "_").replace("\\", "_").replace(" ", "_")
        filename = f"{safe_stem}.png"

        # Full path on disk under data_dir
        out_path = icons_dir / filename
        # Path stored in the database, relative to data_dir so that the
        # /api/v1/application-icons/{application_id}.png endpoint can resolve
        # it by joining with config.data_dir.
        relative_icon_path = Path("application-icons") / filename

        try:
            ok = extract_icon_to_png(str(exe), str(out_path), size=48)
        except Exception as e:
            ok = False
            stats.error_details.append(f"{app.name or exe.name}: extraction error - {e}")

        if not ok or not out_path.exists():
            stats.errors += 1
            if ok and not out_path.exists():
                stats.error_details.append(f"{app.name or exe.name}: icon file was not created")
            continue

        # Compute hash and file size for deduplication/caching
        data = out_path.read_bytes()
        icon_hash = hashlib.sha256(data).hexdigest()
        file_size = out_path.stat().st_size

        # Upsert into application_icons, keeping color and alpha intact. Only
        # the relative path under data_dir is stored in the database.
        try:
            record = app_icon_repo.upsert_application_icon_for_app(
                application_id=app.id,
                source_exe_path=str(exe),
                source_icon_index=0,
                icon_name=app.name or exe.name,
                icon_type="app_png",
                icon_format="png",
                icon_path=str(relative_icon_path),
                icon_width=48,
                icon_height=48,
                preserve_color=True,
                preserve_alpha=True,
                transparent_background=True,
                convert_to_bw=False,
                icon_hash=icon_hash,
                file_size=file_size,
            )
        except Exception as e:
            stats.errors += 1
            stats.error_details.append(f"{app.name or exe.name}: database upsert error - {e}")
            continue

        # Distinguish create vs update via timestamps
        if record.created_at == record.updated_at:
            stats.icons_created += 1
        else:
            stats.icons_updated += 1

    return stats.to_dict()
