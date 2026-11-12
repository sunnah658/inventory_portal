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
    repairs_enabled     INTEGER NOT NULL DEFAULT 0,   -- admin turns the repair log on per department
    attachment_max_mb  INTEGER NOT NULL DEFAULT 10,   -- max size of one file
    created_at         TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name            TEXT NOT NULL,
    designation          TEXT,                         -- job title, shown under the name in the owner signature on invoices, item requests and applications
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash        TEXT NOT NULL,               -- never the real password
    department_id        INTEGER REFERENCES departments(id),
    role                 TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
    must_change_password INTEGER NOT NULL DEFAULT 1,
    is_active            INTEGER NOT NULL DEFAULT 1,
    is_dept_admin        INTEGER NOT NULL DEFAULT 0,   -- sees every record of own department (view + suggest)
    can_ddb_attachment   INTEGER NOT NULL DEFAULT 0,   -- portal admin allows this dept admin to create attachment columns in the dept database
    can_portal_admin     INTEGER NOT NULL DEFAULT 0,   -- portal administrative permission: may do every portal-admin task (see section 24)
    is_deleted           INTEGER NOT NULL DEFAULT 0,   -- soft-deleted: in the Recycle Bin Users tab, work kept 30 days
    deleted_at           TEXT,                         -- when the account was deleted (soft delete)
    deleted_by           INTEGER REFERENCES users(id), -- who deleted the account
    bin_purged           INTEGER NOT NULL DEFAULT 0,   -- removed from the Recycle Bin list, work kept until the 30 days end
    approval_status      TEXT NOT NULL DEFAULT 'approved', -- approved, or pending (dept-admin-created, not functional yet)
    created_by           INTEGER REFERENCES users(id), -- who created the account (for approval notifications)
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
    permission    TEXT NOT NULL DEFAULT 'edit',   -- edit or view (view only)
    PRIMARY KEY (record_id, department_id)
);

-- A record shared with ONE chosen person (edit or view only), independent of departments.
CREATE TABLE IF NOT EXISTS record_user_shares (
    record_id  INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission TEXT NOT NULL DEFAULT 'edit',      -- edit or view (view only)
    shared_by  INTEGER REFERENCES users(id),
    shared_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (record_id, user_id)
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

-- LEGACY (kept, not deleted, not rebuilt — see README section 25):
-- Handover of a record to another user (the receiver must accept).
-- There are no pages or routes for transfers, requests or saved_views
-- in this build; their rows are kept so old data is not lost.
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
    regenerated_at TEXT,
    code_no      INTEGER,                   -- internal sequential number; never reused, never changes, never shown or searched
    code_text    TEXT,                      -- random code HRC-##### (5 digits), shown under the QR and the only code that opens a link
    full_record  INTEGER NOT NULL DEFAULT 0 -- 1 = show every column instead of chosen fields
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

-- ======================= Department database (tabs inside one department database) =======================
CREATE TABLE IF NOT EXISTS ddb_tabs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    template      TEXT,                -- client, meetings, employee, billing, accounts, custom or NULL (old data)
    meeting_notify INTEGER NOT NULL DEFAULT 0,  -- date+time rows in this tab send meeting notifications
    position      INTEGER NOT NULL DEFAULT 0,
    created_by    INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    removed_at    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ddb_tab_name
    ON ddb_tabs(department_id, name COLLATE NOCASE) WHERE removed_at IS NULL;
-- A user a dept admin chose to do everything a dept admin can do in the Department Database.
CREATE TABLE IF NOT EXISTS ddb_delegates (
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    granted_by    INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (department_id, user_id)
);
-- Row sharing: a whole department, or one specific user, with view or edit permission.
CREATE TABLE IF NOT EXISTS ddb_row_shares (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    row_id        INTEGER NOT NULL REFERENCES ddb_rows(id) ON DELETE CASCADE,
    department_id INTEGER REFERENCES departments(id) ON DELETE CASCADE,
    user_id       INTEGER REFERENCES users(id) ON DELETE CASCADE,
    permission    TEXT NOT NULL DEFAULT 'view',
    created_by    INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS ddb_columns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    tab_id        INTEGER REFERENCES ddb_tabs(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    col_type      TEXT NOT NULL CHECK (col_type IN ('text','longtext','number','date','dropdown','yesno','attachment')),
    options       TEXT,
    required      INTEGER NOT NULL DEFAULT 0,
    shown         INTEGER NOT NULL DEFAULT 1,
    has_time      INTEGER NOT NULL DEFAULT 0,
    position      INTEGER NOT NULL DEFAULT 0,
    removed_at    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ddb_column_name
    ON ddb_columns(department_id, tab_id, name COLLATE NOCASE) WHERE removed_at IS NULL;
CREATE TABLE IF NOT EXISTS ddb_rows (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    tab_id        INTEGER REFERENCES ddb_tabs(id) ON DELETE CASCADE,
    owner_id      INTEGER NOT NULL REFERENCES users(id),
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    deleted_at    TEXT,
    deleted_by    INTEGER REFERENCES users(id),
    source_record_id INTEGER,               -- the personal record it was copied from (if any)
    public_code   TEXT,                     -- random HRC-##### share code for the row's public QR
    public_enabled INTEGER NOT NULL DEFAULT 0,
    public_views  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ddb_rows_dept ON ddb_rows(department_id, deleted_at);
CREATE TABLE IF NOT EXISTS ddb_values (
    row_id    INTEGER NOT NULL REFERENCES ddb_rows(id) ON DELETE CASCADE,
    column_id INTEGER NOT NULL REFERENCES ddb_columns(id) ON DELETE CASCADE,
    value     TEXT,
    PRIMARY KEY (row_id, column_id)
);
CREATE TABLE IF NOT EXISTS ddb_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    row_id    INTEGER NOT NULL REFERENCES ddb_rows(id) ON DELETE CASCADE,
    user_id   INTEGER REFERENCES users(id),
    full_name TEXT,
    action    TEXT NOT NULL,
    field     TEXT,
    old_value TEXT,
    new_value TEXT,
    at        TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
-- What each person may do in the department database: view, own (add + manage own rows),
-- edit (edit every row) or manager (does the department admin's tasks). No row = own.
CREATE TABLE IF NOT EXISTS ddb_meeting_sent (
    row_id      INTEGER NOT NULL REFERENCES ddb_rows(id) ON DELETE CASCADE,
    column_id   INTEGER NOT NULL REFERENCES ddb_columns(id) ON DELETE CASCADE,
    value       TEXT NOT NULL,
    offset_days INTEGER NOT NULL,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sent_on     TEXT NOT NULL DEFAULT (date('now','localtime')),
    PRIMARY KEY (row_id, column_id, value, offset_days, user_id)
);
CREATE TABLE IF NOT EXISTS ddb_perms (
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    level         TEXT NOT NULL DEFAULT 'own',
    PRIMARY KEY (department_id, user_id)
);

-- ======================= Invoices (dept-admin templates, employee invoices) =======================
CREATE TABLE IF NOT EXISTS invoice_templates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    created_by    INTEGER REFERENCES users(id),
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'billing',
    title         TEXT NOT NULL DEFAULT 'INVOICE',
    subtitle      TEXT,
    number_prefix TEXT NOT NULL DEFAULT 'BIL',
    next_number   INTEGER NOT NULL DEFAULT 1,
    default_currency TEXT NOT NULL DEFAULT 'BDT',
    vat_percent   REAL NOT NULL DEFAULT 0,
    show_tax      INTEGER NOT NULL DEFAULT 1,
    show_amount_in_words INTEGER NOT NULL DEFAULT 1,
    notes         TEXT,
    show_company_logo INTEGER NOT NULL DEFAULT 1,
    show_address  INTEGER NOT NULL DEFAULT 1,
    company_name  TEXT NOT NULL DEFAULT '',
    company_address TEXT NOT NULL DEFAULT '',
    logo_left     TEXT,
    logo_right    TEXT,
    watermark_on  INTEGER NOT NULL DEFAULT 0,
    watermark_text TEXT,
    signatures_json TEXT NOT NULL DEFAULT '[]',
    top_fields_json TEXT NOT NULL DEFAULT '[]',
    item_columns_json TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'active',
    shared_from_id INTEGER REFERENCES invoice_templates(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS invoices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    tab_id        INTEGER REFERENCES ddb_tabs(id) ON DELETE CASCADE,
    owner_id      INTEGER NOT NULL REFERENCES users(id),
    template_id   INTEGER REFERENCES invoice_templates(id),
    number        TEXT,
    title         TEXT,
    subtitle      TEXT,
    currency      TEXT NOT NULL DEFAULT 'BDT',
    customer_name TEXT,
    customer_address TEXT,
    reference     TEXT,
    invoice_date  TEXT,
    status        TEXT NOT NULL DEFAULT 'draft',
    subtotal      REAL NOT NULL DEFAULT 0,
    vat_amount    REAL NOT NULL DEFAULT 0,
    total         REAL NOT NULL DEFAULT 0,
    amount_in_words TEXT,
    notes         TEXT,
    signatures_json TEXT NOT NULL DEFAULT '[]',
    template_snapshot_json TEXT NOT NULL DEFAULT '{}',
    public_code   TEXT UNIQUE,
    public_enabled INTEGER NOT NULL DEFAULT 0,
    public_views  INTEGER NOT NULL DEFAULT 0,
    public_show_amounts INTEGER NOT NULL DEFAULT 1,
    public_show_customer INTEGER NOT NULL DEFAULT 1,
    public_show_lines INTEGER NOT NULL DEFAULT 0,
    public_expires TEXT,
    void_reason   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS invoice_lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id    INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 0,
    item_name     TEXT,
    description   TEXT,
    qty           REAL NOT NULL DEFAULT 1,
    rate          REAL NOT NULL DEFAULT 0,
    amount        REAL NOT NULL DEFAULT 0,
    line_date     TEXT,
    from_place    TEXT,
    to_place      TEXT,
    mode          TEXT,
    purpose       TEXT,
    spec          TEXT
);
CREATE TABLE IF NOT EXISTS invoice_template_shares (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id   INTEGER NOT NULL REFERENCES invoice_templates(id) ON DELETE CASCADE,
    from_department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    to_department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    shared_by     INTEGER REFERENCES users(id),
    expires       TEXT,
    revoked       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS invoice_dept_shares (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    to_department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    shared_by     INTEGER REFERENCES users(id),
    scope         TEXT NOT NULL DEFAULT 'invoices',
    expires       TEXT,
    revoked       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_records_owner   ON records(owner_id);

-- ======================= Item Requests (dept-admin kinds, user requests to HR & Admin) =======================
CREATE TABLE IF NOT EXISTS item_request_kinds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    created_by    INTEGER REFERENCES users(id),
    name          TEXT NOT NULL,
    number_prefix TEXT NOT NULL DEFAULT 'REQ',
    next_number   INTEGER NOT NULL DEFAULT 1,
    default_currency TEXT NOT NULL DEFAULT 'BDT',
    show_amount_in_words INTEGER NOT NULL DEFAULT 1,
    notes         TEXT,
    show_company_logo INTEGER NOT NULL DEFAULT 1,
    show_address  INTEGER NOT NULL DEFAULT 1,
    company_name  TEXT NOT NULL DEFAULT '',
    company_address TEXT NOT NULL DEFAULT '',
    logo_left     TEXT,
    logo_right    TEXT,
    signatures_json TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS item_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    kind_id       INTEGER REFERENCES item_request_kinds(id),
    owner_id      INTEGER NOT NULL REFERENCES users(id),
    recipient_id  INTEGER REFERENCES users(id),
    number        TEXT,
    currency      TEXT NOT NULL DEFAULT 'BDT',
    request_date  TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    subtotal      REAL NOT NULL DEFAULT 0,
    total         REAL NOT NULL DEFAULT 0,
    amount_in_words TEXT,
    notes         TEXT,
    signatures_json TEXT NOT NULL DEFAULT '[]',
    kind_snapshot_json TEXT NOT NULL DEFAULT '{}',
    public_code   TEXT UNIQUE,
    public_enabled INTEGER NOT NULL DEFAULT 0,
    public_views  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS item_request_lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id    INTEGER NOT NULL REFERENCES item_requests(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 0,
    description   TEXT,
    qty           REAL NOT NULL DEFAULT 1,
    rate          REAL NOT NULL DEFAULT 0,
    amount        REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_req_owner ON item_requests(owner_id);
CREATE INDEX IF NOT EXISTS idx_req_recip ON item_requests(recipient_id);
CREATE INDEX IF NOT EXISTS idx_req_dept  ON item_requests(department_id);
CREATE INDEX IF NOT EXISTS idx_req_code  ON item_requests(public_code);
CREATE TABLE IF NOT EXISTS item_request_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES item_requests(id) ON DELETE CASCADE,
    user_id    INTEGER,
    username   TEXT,
    full_name  TEXT,
    action     TEXT NOT NULL,
    field      TEXT,
    old_value  TEXT,
    new_value  TEXT,
    at         TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_req_hist ON item_request_history(request_id);

--- Application Letters (2026-11-10): kinds made by the dept admin, and the
--- applications users send to one specific HR & Admin user. The HR recipient
--- and the HR & Admin dept admin can edit, set a note, upload a signature
--- and change the status. The document is a formal letter, not an invoice.
CREATE TABLE IF NOT EXISTS application_kinds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    created_by    INTEGER REFERENCES users(id),
    name          TEXT NOT NULL,
    number_prefix TEXT NOT NULL DEFAULT 'LV',
    company_name  TEXT,
    company_address TEXT,
    next_number   INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS applications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    kind_id       INTEGER REFERENCES application_kinds(id),
    owner_id      INTEGER NOT NULL REFERENCES users(id),
    recipient_id  INTEGER REFERENCES users(id),
    checker_id    INTEGER REFERENCES users(id),
    checker_signature_path TEXT,
    checker_signature_at TEXT,
    approver_id   INTEGER REFERENCES users(id),
    number        TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    from_date     TEXT,
    to_date       TEXT,
    days          INTEGER NOT NULL DEFAULT 0,
    reason        TEXT,
    letter_body   TEXT,
    hr_note       TEXT,
    signature_path TEXT,
    signature_by  INTEGER REFERENCES users(id),
    signature_at  TEXT,
    public_code   TEXT UNIQUE,
    public_enabled INTEGER NOT NULL DEFAULT 0,
    public_views  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    deleted_at    TEXT,
    deleted_by    INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS application_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    user_id        INTEGER,
    username       TEXT,
    full_name      TEXT,
    action         TEXT NOT NULL,
    field          TEXT,
    old_value      TEXT,
    new_value      TEXT,
    at             TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_app_kind ON applications(kind_id);
CREATE INDEX IF NOT EXISTS idx_app_owner ON applications(owner_id);
CREATE INDEX IF NOT EXISTS idx_app_recip ON applications(recipient_id);
CREATE INDEX IF NOT EXISTS idx_app_hist ON application_history(application_id);
CREATE INDEX IF NOT EXISTS idx_records_dept    ON records(department_id);
CREATE INDEX IF NOT EXISTS idx_values_column   ON record_values(column_id);
CREATE INDEX IF NOT EXISTS idx_history_record  ON record_history(record_id);
CREATE INDEX IF NOT EXISTS idx_shares_dept     ON record_shares(department_id);
CREATE INDEX IF NOT EXISTS idx_user_shares     ON record_user_shares(user_id);
CREATE INDEX IF NOT EXISTS idx_users_dept      ON users(department_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user   ON login_attempts(username, at);
CREATE INDEX IF NOT EXISTS idx_attempts_ip     ON login_attempts(ip, at);
CREATE INDEX IF NOT EXISTS idx_notif_user      ON notifications(user_id, read_at);
CREATE INDEX IF NOT EXISTS idx_comments_record ON comments(record_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user   ON sessions(user_id);

-- Dashboard settings (2026-11-06): one row per admin, JSON with which
-- dashboard sections that admin wants to see and which chart type (bar/pie)
-- each of the two department charts uses. No row = everything shown, bars.
CREATE TABLE IF NOT EXISTS dashboard_settings (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
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


def _upgrade_repairs_switch(conn):
    """The repair log became a per-department switch. Departments that already have repair
    entries (and the IT department) keep it ON, so nothing disappears; all others start OFF."""
    have = [r["name"] for r in conn.execute("PRAGMA table_info(departments)")]
    if "repairs_enabled" in have:
        return
    conn.execute("ALTER TABLE departments ADD COLUMN repairs_enabled INTEGER NOT NULL DEFAULT 0")
    conn.execute("UPDATE departments SET repairs_enabled=1 WHERE name='IT' OR id IN "
                 "(SELECT DISTINCT r.department_id FROM repairs p JOIN records r ON r.id=p.record_id)")


def _new_random_code_text(conn):
    """A random HRC-##### code (5 digits, 10000-99999) not used by any public link or invoice."""
    import secrets as _secrets
    for _ in range(200):
        cand = f"HRC-{_secrets.randbelow(90000) + 10000}"
        if conn.execute("SELECT 1 FROM public_links WHERE code_text=?", (cand,)).fetchone() is None:
            try:
                if conn.execute("SELECT 1 FROM invoices WHERE public_code=?", (cand,)).fetchone() is None:
                    return cand
            except Exception:
                return cand
    return None


def _upgrade_public_codes(conn):
    """Public QR links get a unique code HRC-0, HRC-1 ... in the order they were created.
    NEW: every link also gets a random HRC-##### code_text, which is what is shown and searched.
    Old code_no values are kept internally only and are never shown or searched any more;
    a link missing code_text is given a random one here, so no link is left code-less."""
    have = [r["name"] for r in conn.execute("PRAGMA table_info(public_links)")]
    if "code_no" not in have:
        conn.execute("ALTER TABLE public_links ADD COLUMN code_no INTEGER")
    if "full_record" not in have:
        conn.execute("ALTER TABLE public_links ADD COLUMN full_record INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_public_code ON public_links(code_no)")
    if "code_text" not in [r["name"] for r in conn.execute("PRAGMA table_info(public_links)")]:
        conn.execute("ALTER TABLE public_links ADD COLUMN code_text TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_public_code_text ON public_links(code_text) WHERE code_text IS NOT NULL")
    for _row in conn.execute("SELECT id FROM public_links WHERE code_text IS NULL OR code_text='' ORDER BY id").fetchall():
        _cand = _new_random_code_text(conn)
        if _cand:
            conn.execute("UPDATE public_links SET code_text=? WHERE id=?", (_cand, _row["id"]))
    nxt = conn.execute("SELECT value FROM settings WHERE key='hrc_next'").fetchone()
    n = int(nxt["value"]) if nxt else 0
    for row in conn.execute("SELECT id FROM public_links WHERE code_no IS NULL ORDER BY id").fetchall():
        conn.execute("UPDATE public_links SET code_no=? WHERE id=?", (n, row["id"]))
        n += 1
    conn.execute("INSERT INTO settings(key,value) VALUES ('hrc_next',?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(n),))


def _upgrade_ddb_attachment_type(conn):
    """Old ddb_columns tables have CHECK(col_type IN (...)) without 'attachment'.
    Recreate the table with the wider CHECK, keeping all rows and the unique index."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='ddb_columns'").fetchone()
    if row is None or "'attachment'" in (row[0] or ""):
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        _has_tab = any(r[1] == "tab_id" for r in conn.execute("PRAGMA table_info(ddb_columns)"))
        conn.execute("CREATE TABLE ddb_columns_new ("
                     "id INTEGER PRIMARY KEY AUTOINCREMENT, department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE, "
                     "tab_id INTEGER REFERENCES ddb_tabs(id) ON DELETE CASCADE, "
                     "name TEXT NOT NULL, col_type TEXT NOT NULL CHECK (col_type IN ('text','longtext','number','date','dropdown','yesno','attachment')), "
                     "options TEXT, required INTEGER NOT NULL DEFAULT 0, shown INTEGER NOT NULL DEFAULT 1, has_time INTEGER NOT NULL DEFAULT 0, "
                     "position INTEGER NOT NULL DEFAULT 0, removed_at TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))")
        if _has_tab:
            conn.execute("INSERT INTO ddb_columns_new(id,department_id,tab_id,name,col_type,options,required,shown,has_time,position,removed_at,created_at) "
                         "SELECT id,department_id,tab_id,name,col_type,options,required,shown,has_time,position,removed_at,created_at FROM ddb_columns")
        else:
            conn.execute("INSERT INTO ddb_columns_new(id,department_id,tab_id,name,col_type,options,required,shown,has_time,position,removed_at,created_at) "
                         "SELECT id,department_id,NULL,name,col_type,options,required,shown,has_time,position,removed_at,created_at FROM ddb_columns")
        conn.execute("DROP TABLE ddb_columns")
        conn.execute("ALTER TABLE ddb_columns_new RENAME TO ddb_columns")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_ddb_column_name ON ddb_columns(department_id, tab_id, name COLLATE NOCASE) WHERE removed_at IS NULL")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _upgrade_invoice_tax_tick(conn):
    """Per-template tax tick (2026-11-05): invoice_templates.show_tax decides
    whether an invoice made from the template offers tax at all. Added only
    once: existing templates are backfilled from their VAT % (a template with
    a VAT % above 0 keeps tax on, the 0 % starters keep it off), and later
    admin changes to the tick are never overwritten by this upgrade."""
    have = [r["name"] for r in conn.execute("PRAGMA table_info(invoice_templates)")]
    if "show_tax" not in have:
        conn.execute("ALTER TABLE invoice_templates ADD COLUMN show_tax INTEGER NOT NULL DEFAULT 1")
        conn.execute("UPDATE invoice_templates SET show_tax = CASE WHEN vat_percent > 0 THEN 1 ELSE 0 END")


def _upgrade_invoice_header(conn):
    """Per-template invoice header (2026-11-05): invoice_templates.company_name
    and company_address let a dept admin choose what appears at the top of
    invoices made from the template. Empty means 'use the portal defaults'
    (portal company name + the default address line, no email), so existing
    templates keep looking as they did, minus the email, until an admin edits
    them. No backfill: nothing is overwritten."""
    have = [r["name"] for r in conn.execute("PRAGMA table_info(invoice_templates)")]
    if "company_name" not in have:
        conn.execute("ALTER TABLE invoice_templates ADD COLUMN company_name TEXT NOT NULL DEFAULT ''")
    if "company_address" not in have:
        conn.execute("ALTER TABLE invoice_templates ADD COLUMN company_address TEXT NOT NULL DEFAULT ''")


def _upgrade_ddb_tabs(conn):
    """Turn the old one-table-per-department database into tabs. Old columns and
    rows (tab_id NULL) go into the department's first admin-created tab when
    one exists; if none exists yet they keep tab_id NULL (data kept in the
    database, not shown) instead of getting a system-made tab.

    The 'General' tab is deleted for everyone (2026-11-05): it was created by
    the upgrade, never by a dept admin, and normal users must only see tabs a
    dept admin created. Any 'General' tab is soft-deleted (removed_at), the
    same as a manual tab delete, so its rows stay in the database. No new
    'General' tab is ever created here, and the DeptDB routes refuse to
    create, rename to, or restore one."""
    _ensure_column(conn, "ddb_columns", "tab_id", "INTEGER REFERENCES ddb_tabs(id) ON DELETE CASCADE")
    _ensure_column(conn, "ddb_rows", "tab_id", "INTEGER REFERENCES ddb_tabs(id) ON DELETE CASCADE")
    _ensure_column(conn, "ddb_rows", "public_code", "TEXT")  # public QR share code (2026-11-09)
    _ensure_column(conn, "ddb_rows", "public_enabled", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "ddb_rows", "public_views", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "ddb_rows", "deleted_by", "INTEGER REFERENCES users(id)")  # who deleted the row, shown in the Recycle Bin (2026-11-10)
    _ensure_column(conn, "applications", "deleted_at", "TEXT")  # soft delete, shown in the Recycle Bin (2026-11-10)
    _ensure_column(conn, "applications", "deleted_by", "INTEGER REFERENCES users(id)")
    _ensure_column(conn, "applications", "checker_id", "INTEGER REFERENCES users(id)")  # own-department checker (two-stage, 2026-11-10)
    _ensure_column(conn, "applications", "checker_signature_path", "TEXT")  # checker's uploaded signature image
    _ensure_column(conn, "applications", "checker_signature_at", "TEXT")  # when the checker signed
    _ensure_column(conn, "applications", "approver_id", "INTEGER REFERENCES users(id)")  # HR & Admin user it was forwarded to
    # The checker/approver indexes live HERE, after the columns above —
    # not in SCHEMA. SCHEMA runs before _ensure_column, so on a database
    # made before build 43 (no checker_id/approver_id yet) the index
    # creation in SCHEMA crashed init_db with "no such column:
    # checker_id" and the container kept restarting (2026-11-12).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_app_checker ON applications(checker_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_app_approver ON applications(approver_id)")
    _ensure_column(conn, "application_kinds", "company_name", "TEXT")  # letterhead company for this kind (2026-11-10)
    _ensure_column(conn, "application_kinds", "company_address", "TEXT")  # letterhead address for this kind
    _ensure_column(conn, "item_request_lines", "item_name", "TEXT")  # item name per line (2026-11-09)
    # per-tab column unique index (old index was department-wide)
    idx = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='ux_ddb_column_name'").fetchone()
    if idx and idx[0] and "tab_id" not in idx[0]:
        conn.execute("DROP INDEX ux_ddb_column_name")
        conn.execute("CREATE UNIQUE INDEX ux_ddb_column_name ON ddb_columns(department_id, tab_id, name COLLATE NOCASE) WHERE removed_at IS NULL")
    # Delete the General tab everywhere (soft delete; rows stay in the database).
    conn.execute("UPDATE ddb_tabs SET removed_at=datetime('now','localtime') "
                 "WHERE LOWER(name)='general' AND removed_at IS NULL")
    depts = [r[0] for r in conn.execute(
        "SELECT DISTINCT department_id FROM ddb_columns WHERE tab_id IS NULL UNION "
        "SELECT DISTINCT department_id FROM ddb_rows WHERE tab_id IS NULL")]
    for dept_id in depts:
        first = conn.execute("SELECT id FROM ddb_tabs WHERE department_id=? AND removed_at IS NULL "
                             "ORDER BY position, id LIMIT 1", (dept_id,)).fetchone()
        if first is None:
            continue
        conn.execute("UPDATE ddb_columns SET tab_id=? WHERE department_id=? AND tab_id IS NULL", (first[0], dept_id))
        conn.execute("UPDATE ddb_rows SET tab_id=? WHERE department_id=? AND tab_id IS NULL", (first[0], dept_id))


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
        _ensure_column(conn, "users", "created_by", "INTEGER REFERENCES users(id)")  # who created the account (2026-11-05)
        _ensure_column(conn, "users", "designation", "TEXT")  # job title, for the owner signature (2026-11-10)
        _ensure_column(conn, "users", "is_dept_admin", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "can_ddb_attachment", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "can_portal_admin", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "deleted_at", "TEXT")
        _ensure_column(conn, "users", "deleted_by", "INTEGER REFERENCES users(id)")
        _ensure_column(conn, "users", "bin_purged", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "approval_status", "TEXT NOT NULL DEFAULT 'approved'")
        _ensure_column(conn, "users", "theme", "TEXT NOT NULL DEFAULT 'auto'")
        _ensure_column(conn, "users", "warn_days", "INTEGER NOT NULL DEFAULT 3")
        _ensure_column(conn, "columns", "has_time", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "record_shares", "permission", "TEXT NOT NULL DEFAULT 'edit'")   # old shares stay 'edit'
        _upgrade_repairs_switch(conn)
        _upgrade_public_codes(conn)
        _upgrade_ddb_attachment_type(conn)
        _upgrade_ddb_tabs(conn)
        _upgrade_invoice_tax_tick(conn)
        _upgrade_invoice_header(conn)
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
                conn.execute("UPDATE departments SET repairs_enabled=1 WHERE id=?", (dept_id,))   # the IT starter has a repair log
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
