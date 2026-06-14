"""Application Library data access for the DisplayPad Server GUI.

This module provides a small repository layer around the `applications`
SQLite table defined in `db.database.initialize_database`.

It is deliberately lightweight so it can be used both from the FastAPI
server and from the PyQt GUI process.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from displaypad_server.core.config import get_config
from displaypad_server.db.database import connect


@dataclass
class ApplicationRecord:
    id: int
    name: str
    executable_path: str
    working_directory: Optional[str]
    arguments: Optional[str]
    icon_path: Optional[str]
    shortcut_path: Optional[str]
    publisher: Optional[str]
    version: Optional[str]
    install_location: Optional[str]
    detection_source: Optional[str]
    enabled: bool
    is_manual: bool
    category: Optional[str]
    notes: Optional[str]
    last_scanned_at: Optional[str]
    created_at: str
    updated_at: str


def _db_path() -> Path:
    """Return the configured SQLite database path.

    Uses the same configuration as the FastAPI server.
    """

    return get_config().database_path


def _row_to_record(row) -> ApplicationRecord:
    return ApplicationRecord(
        id=row["id"],
        name=row["name"],
        executable_path=row["executable_path"],
        working_directory=row["working_directory"],
        arguments=row["arguments"],
        icon_path=row["icon_path"],
        shortcut_path=row["shortcut_path"],
        publisher=row["publisher"],
        version=row["version"],
        install_location=row["install_location"],
        detection_source=row["detection_source"],
        enabled=bool(row["enabled"]),
        is_manual=bool(row["is_manual"]),
        category=row["category"],
        notes=row["notes"],
        last_scanned_at=row["last_scanned_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_applications(*, enabled_only: bool = True, search: Optional[str] = None) -> list[ApplicationRecord]:
    """Return applications from the local library.

    - If ``enabled_only`` is True, returns only enabled apps.
    - If ``search`` is provided, filters by name (case-insensitive LIKE).
    """

    db_path = _db_path()
    with connect(db_path) as conn:
        sql = "SELECT * FROM applications"
        clauses: list[str] = []
        params: list[object] = []

        if enabled_only:
            clauses.append("enabled = 1")

        if search:
            clauses.append("name LIKE ?")
            params.append(f"%{search}%")

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY name COLLATE NOCASE"

        cur = conn.execute(sql, params)
        rows = cur.fetchall()

    return [_row_to_record(row) for row in rows]


def get_application(app_id: int) -> Optional[ApplicationRecord]:
    """Fetch a single application by id, or None if not found."""

    db_path = _db_path()
    with connect(db_path) as conn:
        cur = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_record(row)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_scanned_application(
    *,
    name: str,
    executable_path: str,
    working_directory: Optional[str] = None,
    arguments: Optional[str] = None,
    icon_path: Optional[str] = None,
    shortcut_path: Optional[str] = None,
    publisher: Optional[str] = None,
    version: Optional[str] = None,
    install_location: Optional[str] = None,
    detection_source: Optional[str] = None,
    enabled: bool = True,
) -> ApplicationRecord:
    """Insert or update an auto-detected application.

    We treat ``executable_path`` as the primary identity for *scanned*
    applications. If a non-manual row already exists for this executable,
    it will be updated. Manually created records (``is_manual = 1``) are
    never modified or replaced by scans; if a manual record exists for
    the same executable, it is returned unchanged and no new scanned
    row is created.
    """

    db_path = _db_path()
    now = _utc_now_iso()

    with connect(db_path) as conn:
        # Prefer updating an existing auto-scanned record; do not touch
        # manual records in this function.
        cur = conn.execute(
            "SELECT * FROM applications WHERE executable_path = ? AND is_manual = 0",
            (executable_path,),
        )
        row = cur.fetchone()

        if row:
            conn.execute(
                """
                UPDATE applications SET
                    name = ?,
                    working_directory = ?,
                    arguments = ?,
                    icon_path = ?,
                    shortcut_path = ?,
                    publisher = ?,
                    version = ?,
                    install_location = ?,
                    detection_source = ?,
                    enabled = ?,
                    is_manual = 0,
                    last_scanned_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    name,
                    working_directory,
                    arguments,
                    icon_path,
                    shortcut_path,
                    publisher,
                    version,
                    install_location,
                    detection_source,
                    int(enabled),
                    now,
                    now,
                    row["id"],
                ),
            )

            conn.commit()
            cur = conn.execute("SELECT * FROM applications WHERE id = ?", (row["id"],))
            return _row_to_record(cur.fetchone())

        # If there is an existing manual record for this executable,
        # leave it entirely untouched and simply return it.
        cur = conn.execute(
            "SELECT * FROM applications WHERE executable_path = ? AND is_manual = 1 ORDER BY id DESC LIMIT 1",
            (executable_path,),
        )
        manual_row = cur.fetchone()
        if manual_row:
            return _row_to_record(manual_row)

        # Insert new auto-detected app
        conn.execute(
            """
            INSERT INTO applications (
                name,
                executable_path,
                working_directory,
                arguments,
                icon_path,
                shortcut_path,
                publisher,
                version,
                install_location,
                detection_source,
                enabled,
                is_manual,
                category,
                notes,
                last_scanned_at,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, ?, ?)
            """,
            (
                name,
                executable_path,
                working_directory,
                arguments,
                icon_path,
                shortcut_path,
                publisher,
                version,
                install_location,
                detection_source,
                int(enabled),
                now,
                now,
                now,
            ),
        )
        conn.commit()

        cur = conn.execute(
            "SELECT * FROM applications WHERE executable_path = ?", (executable_path,)
        )
        return _row_to_record(cur.fetchone())


def create_manual_application(
    *,
    name: str,
    executable_path: str,
    working_directory: Optional[str],
    arguments: Optional[str],
    icon_path: Optional[str],
    category: Optional[str],
    notes: Optional[str],
    enabled: bool,
) -> ApplicationRecord:
    """Create a manually-entered application record."""

    db_path = _db_path()
    now = _utc_now_iso()

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO applications (
                name,
                executable_path,
                working_directory,
                arguments,
                icon_path,
                shortcut_path,
                publisher,
                version,
                install_location,
                detection_source,
                enabled,
                is_manual,
                category,
                notes,
                last_scanned_at,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 'manual', ?, 1, ?, ?, NULL, ?, ?)
            """,
            (
                name,
                executable_path,
                working_directory,
                arguments,
                icon_path,
                int(enabled),
                category,
                notes,
                now,
                now,
            ),
        )
        conn.commit()

        cur = conn.execute(
            "SELECT * FROM applications WHERE executable_path = ? ORDER BY id DESC LIMIT 1",
            (executable_path,),
        )
        return _row_to_record(cur.fetchone())


def update_application(
    app_id: int,
    *,
    name: str,
    executable_path: str,
    working_directory: Optional[str],
    arguments: Optional[str],
    icon_path: Optional[str],
    category: Optional[str],
    notes: Optional[str],
    enabled: bool,
) -> None:
    """Update fields for an existing application (manual or scanned)."""

    db_path = _db_path()
    now = _utc_now_iso()

    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE applications SET
                name = ?,
                executable_path = ?,
                working_directory = ?,
                arguments = ?,
                icon_path = ?,
                category = ?,
                notes = ?,
                enabled = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                name,
                executable_path,
                working_directory,
                arguments,
                icon_path,
                category,
                notes,
                int(enabled),
                now,
                app_id,
            ),
        )
        conn.commit()


def set_enabled(app_id: int, enabled: bool) -> None:
    """Enable or disable an application record."""

    db_path = _db_path()
    now = _utc_now_iso()

    with connect(db_path) as conn:
        conn.execute(
            "UPDATE applications SET enabled = ?, updated_at = ? WHERE id = ?",
            (int(enabled), now, app_id),
        )
        conn.commit()


def delete_application(app_id: int) -> None:
    """Permanently delete an application record."""

    db_path = _db_path()

    with connect(db_path) as conn:
        conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        conn.commit()


def clear_applications() -> None:
    """Delete all application records from the library.

    This is primarily used from the GUI "Clear Library" action and is
    intentionally not exposed via any external API endpoint.
    """

    db_path = _db_path()

    with connect(db_path) as conn:
        conn.execute("DELETE FROM applications")
        conn.commit()
