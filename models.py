"""
models.py - database tables, connection helpers and automatic upgrades.

Used by: almost every file.   Uses: config.py
The database is one SQLite file (portal.db). Tables are created automatically on
start (init_db) and older databases are upgraded without losing any data.
"""
import sqlite3

from flask import g, has_app_context, has_request_context, request
from werkzeug.security import generate_password_hash

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL UNIQUE COLLATE NOCASE,
    attachments_enabled INTEGER NOT NULL DEFAULT 0,   -- admin turns this on per department
    attachment_max_mb  INTEGER NOT NULL DEFAULT 10,   -- max size of one file
    created_at         TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name            TEXT NOT NULL,
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash        TEXT NOT NULL,               -- never the real password
    department_id        INTEGER REFERENCES departments(id),
    role                 TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
    must_change_password INTEGER NOT NULL DEFAULT 1,
    is_active            INTEGER NOT NULL DEFAULT 1,
    is_dept_admin        INTEGER NOT NULL DEFAULT 0,   -- sees every record of own department (view + suggest)
    theme                TEXT NOT NULL DEFAULT 'auto', -- light, dark or auto
    warn_days            INTEGER NOT NULL DEFAULT 3,   -- reminder warning: 1, 3 or 7 days ahead
    created_at           TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Departments a user may VIEW (and comment on) besides their own. No editing.
CREATE TABLE IF NOT EXISTS user_view_departments (
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, department_id)
);

-- Record columns: defined by the admin for each department.
CREATE TABLE IF NOT EXISTS columns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    col_type      TEXT NOT NULL CHECK (col_type IN
                  ('text','longtext','number','date','dropdown','yesno')),
    options       TEXT,                 -- dropdown choices, one per line
    required      INTEGER NOT NULL DEFAULT 0,
    shown         INTEGER NOT NULL DEFAULT 1,
    position      INTEGER NOT NULL DEFAULT 0,
    protected     INTEGER NOT NULL DEFAULT 0,   -- accidental delete protection
    is_reminder   INTEGER NOT NULL DEFAULT 0,   -- this date sends reminders (any number per department)
    has_time      INTEGER NOT NULL DEFAULT 0,   -- date column that also keeps a time (meetings)
    removed_at    TEXT,                 -- set = "removed" (hidden, data kept)
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_column_name
    ON columns(department_id, name COLLATE NOCASE) WHERE removed_at IS NULL;

-- A record belongs to the department of the person who created it.
CREATE TABLE IF NOT EXISTS records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id      INTEGER NOT NULL REFERENCES users(id),
    department_id INTEGER NOT NULL REFERENCES departments(id),
    version       INTEGER NOT NULL DEFAULT 1,   -- used to detect two people editing at once
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    deleted_at    TEXT,                          -- set = in the recycle bin
    deleted_by    INTEGER REFERENCES users(id)
);

-- The values of a record: one row per filled column (blank = no row).
CREATE TABLE IF NOT EXISTS record_values (
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    column_id INTEGER NOT NULL REFERENCES columns(id) ON DELETE CASCADE,
    value     TEXT,
    PRIMARY KEY (record_id, column_id)
);

-- Departments a record is shared with (their members can view and edit it).
CREATE TABLE IF NOT EXISTS record_shares (
    record_id     INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    shared_by     INTEGER REFERENCES users(id),
    shared_at     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (record_id, department_id)
);

-- Edit history: who changed what and when. Never edited or deleted by the portal.
CREATE TABLE IF NOT EXISTS record_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id  INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    user_id    INTEGER,
    username   TEXT,
    full_name  TEXT,
    action     TEXT NOT NULL,
    field      TEXT,
    old_value  TEXT,
    new_value  TEXT,
    at         TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS repairs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id  INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    date_in    TEXT,
    problem    TEXT,
    fixed_by   TEXT,
    cost       TEXT,
    date_back  TEXT,                 -- empty = still in repair
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS attachments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id     INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    stored_name   TEXT NOT NULL,     -- random name on disk
    size          INTEGER NOT NULL,
    uploaded_by   INTEGER REFERENCES users(id),
    scan_status   TEXT,              -- clean, or empty when scanning was off
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS activity_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    username   TEXT,
    action     TEXT NOT NULL,
    details    TEXT,
    ip         TEXT,                 -- computer the action came from
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Logged-in browsers. Lets the admin see and end sessions and enforces the idle timeout.
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ip         TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_seen  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    revoked    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    ip       TEXT,
    success  INTEGER NOT NULL,
    at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Comments and suggestions on a record (separate from the edit history).
CREATE TABLE IF NOT EXISTS comments (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    kind      TEXT NOT NULL DEFAULT 'comment',     -- comment or suggestion
    text      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    link       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    read_at    TEXT
);

-- Handover of a record to another user (the receiver must accept).
CREATE TABLE IF NOT EXISTS transfers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    from_user   INTEGER NOT NULL REFERENCES users(id),
    to_user     INTEGER NOT NULL REFERENCES users(id),
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending, accepted, declined, cancelled
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    resolved_at TEXT
);

-- Requests that need approval (new item, repair, other).
CREATE TABLE IF NOT EXISTS requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id  INTEGER NOT NULL REFERENCES users(id),
    department_id INTEGER REFERENCES departments(id),
    kind          TEXT NOT NULL DEFAULT 'other',
    title         TEXT NOT NULL,
    details       TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending, approved, rejected, cancelled
    decided_by    INTEGER REFERENCES users(id),
    decided_at    TEXT,
    decision_note TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Public QR links: anyone with the link sees ONLY the chosen fields, read-only.
CREATE TABLE IF NOT EXISTS public_links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token        TEXT NOT NULL UNIQUE,      -- long random code in the link
    owner_id     INTEGER NOT NULL REFERENCES users(id),
    title        TEXT,
    kind         TEXT NOT NULL DEFAULT 'single',   -- single record or group of records
    fields       TEXT NOT NULL DEFAULT '',  -- chosen column names, one per line (lower case)
    enabled      INTEGER NOT NULL DEFAULT 1,
    views        INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    regenerated_at TEXT
);
CREATE TABLE IF NOT EXISTS public_link_records (
    link_id   INTEGER NOT NULL REFERENCES public_links(id) ON DELETE CASCADE,
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    PRIMARY KEY (link_id, record_id)
);

-- Saved filters and sorting ("saved views") of the record lists.
CREATE TABLE IF NOT EXISTS saved_views (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    page       TEXT NOT NULL,
    name       TEXT NOT NULL,
    query      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Which reminder notifications were already sent (so nobody gets the same one twice).
-- The date/time VALUE is part of the key: when a meeting is moved, new reminders are sent.
CREATE TABLE IF NOT EXISTS reminder_sent (
    record_id   INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    column_id   INTEGER NOT NULL REFERENCES columns(id) ON DELETE CASCADE,
    value       TEXT NOT NULL,
    offset_days INTEGER NOT NULL,
    sent_on     TEXT NOT NULL DEFAULT (date('now','localtime')),
    PRIMARY KEY (record_id, column_id, value, offset_days)
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE INDEX IF NOT EXISTS idx_records_owner   ON records(owner_id);
CREATE INDEX IF NOT EXISTS idx_records_dept    ON records(department_id);
CREATE INDEX IF NOT EXISTS idx_values_column   ON record_values(column_id);
CREATE INDEX IF NOT EXISTS idx_history_record  ON record_history(record_id);
CREATE INDEX IF NOT EXISTS idx_shares_dept     ON record_shares(department_id);
CREATE INDEX IF NOT EXISTS idx_users_dept      ON users(department_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user   ON login_attempts(username, at);
CREATE INDEX IF NOT EXISTS idx_attempts_ip     ON login_attempts(ip, at);
CREATE INDEX IF NOT EXISTS idx_notif_user      ON notifications(user_id, read_at);
CREATE INDEX IF NOT EXISTS idx_comments_record ON comments(record_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user   ON sessions(user_id);
"""


def connect():
    """Open a SQLite connection with the safe settings for many users."""
    conn = sqlite3.connect(config.DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")     # readers do not block the writer
    conn.execute("PRAGMA busy_timeout=5000")    # wait up to 5 s when the DB is busy
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    """One connection per web request (closed automatically afterwards)."""
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)


def _table_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _ensure_column(conn, table, column, ddl):
    """Add a column to an older table if it is missing (keeps existing data)."""
    have = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    if column not in have:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


# Old versions kept equipment in one fixed table. These are turned into normal columns.
_LEGACY_FIELDS = [
    ("asset_tag", "Asset tag", "text"), ("name", "Equipment name", "text"),
    ("type", "Type", "text"), ("brand", "Brand", "text"), ("model", "Model", "text"),
    ("serial_no", "Serial no", "text"), ("location", "Location", "text"),
    ("status", "Status", "dropdown"), ("purchase_date", "Purchase date", "date"),
    ("remarks", "Remarks", "longtext"),
]


def _migrate_legacy_equipment(conn):
    """Copy rows of the old 'equipment' table into the new records structure."""
    if not _table_exists(conn, "equipment"):
        return
    rows = conn.execute("SELECT * FROM equipment").fetchall()
    col_ids = {}                      # (department_id, field) -> column id
    for r in rows:
        dept = r["department_id"] or conn.execute(
            "SELECT department_id FROM users WHERE id=?", (r["owner_id"],)).fetchone()[0]
        if dept is None:
            continue
        if (dept, "asset_tag") not in col_ids:           # create the columns once per department
            for pos, (field, label, ctype) in enumerate(_LEGACY_FIELDS):
                opts = "In use\nIn stock\nUnder repair\nDamaged\nRetired" if ctype == "dropdown" else None
                col_ids[(dept, field)] = conn.execute(
                    "INSERT INTO columns(department_id,name,col_type,options,position,protected)"
                    " VALUES (?,?,?,?,?,1)", (dept, label, ctype, opts, pos)).lastrowid
        rid = conn.execute(
            "INSERT INTO records(owner_id,department_id,created_at,updated_at) VALUES (?,?,?,?)",
            (r["owner_id"], dept, r["updated_at"], r["updated_at"])).lastrowid
        for field, _label, _t in _LEGACY_FIELDS:
            if r[field]:
                conn.execute("INSERT INTO record_values(record_id,column_id,value) VALUES (?,?,?)",
                             (rid, col_ids[(dept, field)], r[field]))
        conn.execute("INSERT INTO record_history(record_id,action,new_value,at)"
                     " VALUES (?, 'created', 'Imported from the older portal version', ?)",
                     (rid, r["updated_at"]))
    conn.execute("ALTER TABLE equipment RENAME TO equipment_old")   # keep it as a safety copy


def init_db():
    """Create tables, upgrade old databases and create the first admin."""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "departments", "attachments_enabled", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "departments", "attachment_max_mb", "INTEGER NOT NULL DEFAULT 10")
        _ensure_column(conn, "users", "is_dept_admin", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "theme", "TEXT NOT NULL DEFAULT 'auto'")
        _ensure_column(conn, "users", "warn_days", "INTEGER NOT NULL DEFAULT 3")
        _ensure_column(conn, "columns", "has_time", "INTEGER NOT NULL DEFAULT 0")
        conn.execute("DROP INDEX IF EXISTS ux_column_reminder")   # several reminder columns are allowed now
        _ensure_column(conn, "activity_log", "ip", "TEXT")
        _ensure_column(conn, "attachments", "scan_status", "TEXT")
        _migrate_legacy_equipment(conn)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            row = conn.execute("SELECT id FROM departments WHERE name=?",
                               (config.DEFAULT_DEPARTMENT,)).fetchone()
            dept_id = row["id"] if row else conn.execute(
                "INSERT INTO departments(name) VALUES (?)", (config.DEFAULT_DEPARTMENT,)).lastrowid
            if not row:                                  # give the first department the IT starter columns
                from core import create_department_columns
                create_department_columns(conn, dept_id, "IT")
            conn.execute(
                "INSERT INTO users(full_name,username,password_hash,department_id,role,"
                "must_change_password) VALUES (?,?,?,?, 'admin', 1)",
                (config.DEFAULT_ADMIN_NAME, config.DEFAULT_ADMIN_USERNAME,
                 generate_password_hash(config.DEFAULT_ADMIN_PASSWORD), dept_id))
        conn.commit()
    finally:
        conn.close()


def log(db, action, details="", username=None, ip=None):
    """Write one line in the activity log: who, what and from which computer (IP address)."""
    user = g.get("user") if has_app_context() else None
    if ip is None and has_request_context():
        ip = request.remote_addr
    db.execute("INSERT INTO activity_log(user_id,username,action,details,ip) VALUES (?,?,?,?,?)",
               (user["id"] if user else None, username or (user["username"] if user else None),
                action, details, ip))


def setting_get(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def setting_set(db, key, value):
    db.execute("INSERT INTO settings(key,value) VALUES (?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
