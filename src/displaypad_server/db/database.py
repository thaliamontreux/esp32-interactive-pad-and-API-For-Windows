import sqlite3
from pathlib import Path


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database(database_path: Path) -> None:
    with connect(database_path) as conn:
        # App metadata for API identity
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        # Applications table for Windows host application library
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                executable_path TEXT NOT NULL,
                working_directory TEXT,
                arguments TEXT,
                icon_path TEXT,
                shortcut_path TEXT,
                publisher TEXT,
                version TEXT,
                install_location TEXT,
                detection_source TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                is_manual INTEGER NOT NULL DEFAULT 0,
                category TEXT,
                notes TEXT,
                last_scanned_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                usage_score INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # Pads/devices table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pad_uuid TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'button_pad',
                screen_width INTEGER NOT NULL,
                screen_height INTEGER NOT NULL,
                screen_driver TEXT NOT NULL,
                button_count INTEGER NOT NULL DEFAULT 6,
                page_count INTEGER NOT NULL DEFAULT 1,
                page_button_counts TEXT,
                token_hash TEXT,
                encrypted_token TEXT,
                api_fingerprint TEXT,
                paired_at TEXT,
                last_seen TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                revoked INTEGER NOT NULL DEFAULT 0,
                config_version INTEGER NOT NULL DEFAULT 1,
                last_config_downloaded INTEGER DEFAULT 0,
                update_pending INTEGER NOT NULL DEFAULT 0,
                update_required INTEGER NOT NULL DEFAULT 0,
                websocket_connected INTEGER NOT NULL DEFAULT 0,
                last_update_status TEXT,
                last_update_error TEXT,
                control_panel_pin_hash TEXT,
                control_panel_pin_length INTEGER NOT NULL DEFAULT 8,
                default_pin_active INTEGER NOT NULL DEFAULT 1,
                pin_max_attempts INTEGER NOT NULL DEFAULT 5,
                pin_lockout_seconds INTEGER NOT NULL DEFAULT 300,
                last_ip TEXT,
                time_use_24h INTEGER NOT NULL DEFAULT 0,
                time_show_am_pm INTEGER NOT NULL DEFAULT 1
            )
            """
        )

        # Backward-compatible migration: ensure new columns exist on older DBs
        try:
            conn.execute("ALTER TABLE pads ADD COLUMN last_ip TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE pads ADD COLUMN time_use_24h INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE pads ADD COLUMN time_show_am_pm INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass

        # Per-page layout support
        try:
            conn.execute("ALTER TABLE pads ADD COLUMN page_count INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE pads ADD COLUMN page_button_counts TEXT")
        except Exception:
            pass

        # Backward-compatible migration: ensure usage_score exists on older
        # applications tables so that common-app tracking can work without
        # requiring a full DB reset.
        try:
            conn.execute("ALTER TABLE applications ADD COLUMN usage_score INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass

        # Buttons table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pad_id INTEGER NOT NULL,
                slot INTEGER NOT NULL,
                label TEXT NOT NULL,
                icon_id TEXT,
                action_id TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                bg_color INTEGER,
                icon_color INTEGER,
                text_color INTEGER,
                show_text INTEGER NOT NULL DEFAULT 1,
                -- Optional application snapshot fields for "Launch Application" actions
                application_id INTEGER,
                application_name TEXT,
                executable_path TEXT,
                working_directory TEXT,
                arguments TEXT,
                override_arguments TEXT,
                icon_path TEXT,
                run_mode TEXT,
                launch_source_snapshot_time TEXT,
                source TEXT,
                UNIQUE(pad_id, slot),
                FOREIGN KEY(pad_id) REFERENCES pads(id)
            )
            """
        )

        # ESP32 log sessions (one per device reboot) and raw log lines. These
        # are used to store per-pad console output streamed over WebSocket so
        # the GUI can display historical logs for each device.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS log_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pad_id INTEGER NOT NULL,
                pad_uuid TEXT NOT NULL,
                session_uuid TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                reboot_reason TEXT,
                fw_version TEXT,
                FOREIGN KEY(pad_id) REFERENCES pads(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                pad_id INTEGER NOT NULL,
                pad_uuid TEXT NOT NULL,
                seq INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                level TEXT,
                message TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES log_sessions(id),
                FOREIGN KEY(pad_id) REFERENCES pads(id)
            )
            """
        )

        # Basic indexes to keep log queries responsive
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_log_sessions_pad ON log_sessions(pad_id, started_at DESC)")
        except Exception:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_session_seq ON logs(session_id, seq)")
        except Exception:
            pass

        # Backward-compatible migration: ensure new button color columns exist
        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN bg_color INTEGER")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN icon_color INTEGER")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN text_color INTEGER")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN show_text INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass

        # Application snapshot fields for launch actions (backward-compatible)
        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN application_id INTEGER")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN application_name TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN executable_path TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN working_directory TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN arguments TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN override_arguments TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN icon_path TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN run_mode TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN launch_source_snapshot_time TEXT")
        except Exception:
            pass

        try:
            conn.execute("ALTER TABLE buttons ADD COLUMN source TEXT")
        except Exception:
            pass

        # Macros table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS macros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                permission_level TEXT NOT NULL DEFAULT 'normal'
            )
            """
        )

        # Task pad profiles
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_pad_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pad_id INTEGER NOT NULL UNIQUE,
                priority_processes_json TEXT NOT NULL DEFAULT '[]',
                show_non_priority INTEGER NOT NULL DEFAULT 1,
                max_tasks INTEGER NOT NULL DEFAULT 32,
                FOREIGN KEY(pad_id) REFERENCES pads(id)
            )
            """
        )

        # Icons table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS icons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                icon_id TEXT NOT NULL UNIQUE,
                source TEXT,
                png_path TEXT,
                updated_at TEXT
            )
            """
        )

        # Windows application icons (separate from the 2-bit icon system)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS application_icons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                source_exe_path TEXT NOT NULL,
                source_icon_index INTEGER NOT NULL DEFAULT 0,
                icon_name TEXT,
                icon_type TEXT NOT NULL,
                icon_format TEXT NOT NULL,
                icon_path TEXT NOT NULL,
                icon_width INTEGER NOT NULL,
                icon_height INTEGER NOT NULL,
                preserve_color INTEGER NOT NULL DEFAULT 1,
                preserve_alpha INTEGER NOT NULL DEFAULT 1,
                transparent_background INTEGER NOT NULL DEFAULT 1,
                convert_to_bw INTEGER NOT NULL DEFAULT 0,
                icon_hash TEXT,
                file_size INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(application_id) REFERENCES applications(id)
            )
            """
        )

        # Audit log
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pad_id INTEGER,
                event_type TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        # Pairing sessions
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pairing_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pairing_code_hash TEXT NOT NULL,
                api_uuid TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )

        # Pad config history
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pad_config_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pad_id INTEGER NOT NULL,
                config_version INTEGER NOT NULL,
                config_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT,
                applied_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY(pad_id) REFERENCES pads(id)
            )
            """
        )

        # Nonce cache for replay protection
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nonce_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pad_id INTEGER NOT NULL,
                nonce TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(pad_id, nonce)
            )
            """
        )

        conn.commit()


def get_connection(database_path: Path) -> sqlite3.Connection:
    return connect(database_path)
