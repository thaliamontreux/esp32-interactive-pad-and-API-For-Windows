from __future__ import annotations

from datetime import datetime
from pathlib import Path

from displaypad_server.core.config import get_config
from displaypad_server.db.database import connect


ICON_EXTENSIONS = {".png"}


def sync_icons_from_folder() -> None:
    """Scan the icons folder and synchronize the icons table.

    - Uses each filename (without extension) as icon_id.
    - Stores a relative png_path under the configured data_dir when possible.
    - Removes icons from the table if the file no longer exists.
    """
    config = get_config()
    data_dir = Path(config.data_dir)

    # Icons live in a top-level "icons" folder at the project root (alongside src/, data/, etc.),
    # not under data_dir. __file__ is src/displaypad_server/core/icons_sync.py, so parents[3]
    # is the project root; from there we point to root/icons.
    # We store png_path relative to data_dir as "../icons/<filename>" so the existing
    # /api/v1/icons/{icon_id}.png endpoint can resolve it correctly.
    icons_dir = Path(__file__).resolve().parents[3] / "icons"

    if not icons_dir.exists() or not icons_dir.is_dir():
        return

    # Discover all PNG files in the icons directory (non-recursive)
    files = [p for p in icons_dir.iterdir() if p.is_file() and p.suffix.lower() in ICON_EXTENSIONS]

    # Build desired state: {icon_id: relative_png_path}
    desired: dict[str, str] = {}
    for p in files:
        icon_id = p.stem  # filename without extension
        # Store path relative to data_dir so get_icon can resolve it
        try:
            rel = p.relative_to(data_dir)
        except ValueError:
            # p is not under data_dir; store as ../icons/<name>
            rel = Path("..") / "icons" / p.name
        desired[icon_id] = str(rel).replace("\\", "/")

    now = datetime.utcnow().isoformat(timespec="seconds")

    with connect(config.database_path) as conn:
        # Load existing icons
        cursor = conn.execute("SELECT icon_id, png_path FROM icons")
        existing_rows = cursor.fetchall()
        existing = {row["icon_id"]: row["png_path"] for row in existing_rows}

        # Delete icons that no longer have a file
        for icon_id in list(existing.keys()):
            if icon_id not in desired:
                conn.execute("DELETE FROM icons WHERE icon_id = ?", (icon_id,))

        # Insert or update icons from desired set
        for icon_id, png_path in desired.items():
            if icon_id in existing:
                if existing[icon_id] != png_path:
                    conn.execute(
                        "UPDATE icons SET png_path = ?, updated_at = ? WHERE icon_id = ?",
                        (png_path, now, icon_id),
                    )
            else:
                conn.execute(
                    "INSERT INTO icons (icon_id, source, png_path, updated_at) VALUES (?, ?, ?, ?)",
                    (icon_id, "filesystem", png_path, now),
                )

        conn.commit()
