# Database Schema

Database: SQLite

## pads

```sql
CREATE TABLE IF NOT EXISTS pads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pad_uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'button_pad',
    screen_width INTEGER NOT NULL,
    screen_height INTEGER NOT NULL,
    screen_driver TEXT NOT NULL,
    button_count INTEGER NOT NULL DEFAULT 6,
    token_hash TEXT,
    encrypted_token TEXT,  -- XOR encrypted device token for HMAC verification
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
    pin_lockout_seconds INTEGER NOT NULL DEFAULT 300
);

**Note**: `encrypted_token` stores the device token encrypted with XOR using a key derived from the API secret.
This allows HMAC signature verification while protecting the token at rest.

## buttons

```sql
CREATE TABLE IF NOT EXISTS buttons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pad_id INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    label TEXT NOT NULL,
    icon_id TEXT,
    action_id TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(pad_id, slot),
    FOREIGN KEY(pad_id) REFERENCES pads(id)
);
```

## macros

```sql
CREATE TABLE IF NOT EXISTS macros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    permission_level TEXT NOT NULL DEFAULT 'normal'
);
```

## task_pad_profiles

```sql
CREATE TABLE IF NOT EXISTS task_pad_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pad_id INTEGER NOT NULL UNIQUE,
    priority_processes_json TEXT NOT NULL DEFAULT '[]',
    show_non_priority INTEGER NOT NULL DEFAULT 1,
    max_tasks INTEGER NOT NULL DEFAULT 32,
    FOREIGN KEY(pad_id) REFERENCES pads(id)
);
```

## icons

```sql
CREATE TABLE IF NOT EXISTS icons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    icon_id TEXT NOT NULL UNIQUE,
    source TEXT,
    png_path TEXT,
    updated_at TEXT
);
```

## audit_log

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pad_id INTEGER,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

## pairing_sessions

```sql
CREATE TABLE IF NOT EXISTS pairing_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pairing_code_hash TEXT NOT NULL,
    api_uuid TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
```

## pad_config_history

```sql
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
);
```

## nonce_cache

```sql
CREATE TABLE IF NOT EXISTS nonce_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pad_id INTEGER NOT NULL,
    nonce TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(pad_id, nonce)
);
```
