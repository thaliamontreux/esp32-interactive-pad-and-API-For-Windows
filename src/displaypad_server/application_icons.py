from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from displaypad_server.core.config import get_config
from displaypad_server.db.database import connect


@dataclass
class ApplicationIconRecord:
    id: int
    application_id: int
    source_exe_path: str
    source_icon_index: int
    icon_name: Optional[str]
    icon_type: str
    icon_format: str
    icon_path: str
    icon_width: int
    icon_height: int
    preserve_color: bool
    preserve_alpha: bool
    transparent_background: bool
    convert_to_bw: bool
    icon_hash: Optional[str]
    file_size: Optional[int]
    created_at: str
    updated_at: str


def _db_path() -> Path:
    return get_config().database_path


def _row_to_record(row) -> ApplicationIconRecord:
    return ApplicationIconRecord(
        id=row["id"],
        application_id=row["application_id"],
        source_exe_path=row["source_exe_path"],
        source_icon_index=row["source_icon_index"],
        icon_name=row["icon_name"],
        icon_type=row["icon_type"],
        icon_format=row["icon_format"],
        icon_path=row["icon_path"],
        icon_width=row["icon_width"],
        icon_height=row["icon_height"],
        preserve_color=bool(row["preserve_color"]),
        preserve_alpha=bool(row["preserve_alpha"]),
        transparent_background=bool(row["transparent_background"]),
        convert_to_bw=bool(row["convert_to_bw"]),
        icon_hash=row["icon_hash"],
        file_size=row["file_size"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_primary_icon_for_application(application_id: int) -> Optional[ApplicationIconRecord]:
    """Return the primary PNG icon for a given application, if any."""

    db_path = _db_path()
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT * FROM application_icons
            WHERE application_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (application_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_record(row)


def get_primary_icon_for_executable(executable_path: str) -> Optional[ApplicationIconRecord]:
    """Return the primary PNG icon for a given executable path, if any.

    This is a fallback path used when a button's application_id is not
    available but we still have an executable path snapshot stored.
    """

    db_path = _db_path()
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT * FROM application_icons
            WHERE source_exe_path = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (executable_path,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_record(row)


def upsert_application_icon_for_app(
    application_id: int,
    *,
    source_exe_path: str,
    source_icon_index: int,
    icon_name: Optional[str],
    icon_type: str,
    icon_format: str,
    icon_path: str,
    icon_width: int,
    icon_height: int,
    preserve_color: bool,
    preserve_alpha: bool,
    transparent_background: bool,
    convert_to_bw: bool,
    icon_hash: Optional[str],
    file_size: Optional[int],
) -> ApplicationIconRecord:
    """Insert or update a PNG icon record for a specific application.

    We treat (application_id, icon_type, source_exe_path, source_icon_index)
    as the identity for a single imported icon. This keeps monochrome
    firmware icons separate from Windows application PNG icons.
    """

    db_path = _db_path()
    now = _utc_now_iso()

    key = (application_id, icon_type, source_exe_path, source_icon_index)

    with connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT * FROM application_icons
            WHERE application_id = ?
              AND icon_type = ?
              AND source_exe_path = ?
              AND source_icon_index = ?
            LIMIT 1
            """,
            key,
        )
        row = cur.fetchone()

        if row:
            conn.execute(
                """
                UPDATE application_icons SET
                    icon_name = ?,
                    icon_format = ?,
                    icon_path = ?,
                    icon_width = ?,
                    icon_height = ?,
                    preserve_color = ?,
                    preserve_alpha = ?,
                    transparent_background = ?,
                    convert_to_bw = ?,
                    icon_hash = ?,
                    file_size = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    icon_name,
                    icon_format,
                    icon_path,
                    icon_width,
                    icon_height,
                    int(preserve_color),
                    int(preserve_alpha),
                    int(transparent_background),
                    int(convert_to_bw),
                    icon_hash,
                    file_size,
                    now,
                    row["id"],
                ),
            )
            conn.commit()
            cur = conn.execute("SELECT * FROM application_icons WHERE id = ?", (row["id"],))
            return _row_to_record(cur.fetchone())

        # Insert new icon record
        conn.execute(
            """
            INSERT INTO application_icons (
                application_id,
                source_exe_path,
                source_icon_index,
                icon_name,
                icon_type,
                icon_format,
                icon_path,
                icon_width,
                icon_height,
                preserve_color,
                preserve_alpha,
                transparent_background,
                convert_to_bw,
                icon_hash,
                file_size,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                source_exe_path,
                source_icon_index,
                icon_name,
                icon_type,
                icon_format,
                icon_path,
                icon_width,
                icon_height,
                int(preserve_color),
                int(preserve_alpha),
                int(transparent_background),
                int(convert_to_bw),
                icon_hash,
                file_size,
                now,
                now,
            ),
        )
        conn.commit()

        cur = conn.execute(
            """
            SELECT * FROM application_icons
            WHERE application_id = ?
              AND icon_type = ?
              AND source_exe_path = ?
              AND source_icon_index = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            key,
        )
        return _row_to_record(cur.fetchone())
