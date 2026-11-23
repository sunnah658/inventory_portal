"""
models.py - database tables, connection helpers and automatic upgrades.

Used by: almost every file.   Uses: config.py
The database is MySQL (see dbapi.py and config.py for the connection
settings). Tables are created automatically on start (init_db) and older
databases are upgraded without losing any data.
"""
import dbapi

from flask import g, has_app_context, has_request_context, request
from werkzeug.security import generate_password_hash

import config

SCHEMA = """
-- MySQL schema for the portal (build 67). Converted from the SQLite
-- SCHEMA in models.py. Differences from SQLite, by design:
--   * INT AUTO_INCREMENT PRIMARY KEY (was INTEGER PRIMARY KEY AUTOINCREMENT)
--   * System timestamps are DATETIME DEFAULT CURRENT_TIMESTAMP (was TEXT
--     DEFAULT (datetime('now','localtime'))); dates are DATE.
--   * User-entered dates (invoice_date, request_date, ...) stay
--     VARCHAR(255): they hold a date string or an empty string.
--   * Short TEXT columns with a short default are VARCHAR(255) (MySQL
--     TEXT columns cannot have a DEFAULT); JSON/long TEXT columns with a
--     '[]'/'{}'/'' default are plain TEXT (nullable) — the code reads
--     them with `or "[]"` / `or "{}"`, so NULL is safe.
--   * Inline REFERENCES are explicit FOREIGN KEY ... ON DELETE CASCADE
--     (MySQL ignores inline REFERENCES).
--   * SQLite's partial unique indexes (WHERE removed_at IS NULL) do not
--     exist in MySQL: they are a generated column (the name when the row
--     is live, NULL when removed) plus a UNIQUE KEY on it. A unique key
--     ignores NULLs, so removed rows never conflict — exactly the
--     SQLite behaviour.
--   * `settings.key` is renamed `setting_key`: KEY is a reserved word
--     in MySQL and cannot be used unquoted.
--   * Tables are ordered so a referenced table is created before the
--     table that references it (MySQL, unlike SQLite, refuses a
--     foreign key to a table that does not exist yet).
--   * All indexes are inline in the CREATE TABLE (MySQL has no
--     CREATE INDEX IF NOT EXISTS), so CREATE TABLE IF NOT EXISTS stays
--     idempotent.

CREATE TABLE IF NOT EXISTS departments (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    name                VARCHAR(255) NOT NULL UNIQUE,
    attachments_enabled INT NOT NULL DEFAULT 0,
    repairs_enabled     INT NOT NULL DEFAULT 0,
    attachment_max_mb   INT NOT NULL DEFAULT 10,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    full_name            VARCHAR(255) NOT NULL,
    designation          VARCHAR(255),
    username             VARCHAR(255) NOT NULL UNIQUE,
    password_hash        VARCHAR(255) NOT NULL,
    email                VARCHAR(255),
    phone                VARCHAR(255),
    department_id        INT,
    role                 VARCHAR(255) NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
    must_change_password INT NOT NULL DEFAULT 1,
    is_active            INT NOT NULL DEFAULT 1,
    is_dept_admin        INT NOT NULL DEFAULT 0,
    can_ddb_attachment   INT NOT NULL DEFAULT 0,
    can_portal_admin     INT NOT NULL DEFAULT 0,
    is_deleted           INT NOT NULL DEFAULT 0,
    deleted_at           DATETIME,
    deleted_by           INT,
    bin_purged           INT NOT NULL DEFAULT 0,
    approval_status      VARCHAR(255) NOT NULL DEFAULT 'approved',
    created_by           INT,
    theme                VARCHAR(255) NOT NULL DEFAULT 'auto',
    warn_days            INT NOT NULL DEFAULT 3,
    signature_path       VARCHAR(255),
    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (department_id) REFERENCES departments(id),
    FOREIGN KEY (deleted_by) REFERENCES users(id),
    FOREIGN KEY (created_by) REFERENCES users(id),
    KEY idx_users_dept (department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Departments a user may VIEW (and comment on) besides their own. No editing.
CREATE TABLE IF NOT EXISTS user_view_departments (
    user_id       INT NOT NULL,
    department_id INT NOT NULL,
    PRIMARY KEY (user_id, department_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Record columns: defined by the admin for each department.
CREATE TABLE IF NOT EXISTS columns (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    user_id       INT,
    name          VARCHAR(255) NOT NULL,
    col_type      VARCHAR(255) NOT NULL CHECK (col_type IN
                  ('text','longtext','number','date','dropdown','yesno','attachment')),
    options       TEXT,
    required      INT NOT NULL DEFAULT 0,
    shown         INT NOT NULL DEFAULT 1,
    position      INT NOT NULL DEFAULT 0,
    protected     INT NOT NULL DEFAULT 0,
    is_reminder   INT NOT NULL DEFAULT 0,
    has_time      INT NOT NULL DEFAULT 0,
    removed_at    DATETIME,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Partial unique indexes (SQLite) as generated columns: the name
    -- when the row is live, NULL when removed. A unique key ignores
    -- NULLs, so a removed column never blocks a new one with its name.
    name_dept     VARCHAR(255) GENERATED ALWAYS AS
                  (CASE WHEN removed_at IS NULL AND user_id IS NULL THEN name ELSE NULL END) STORED,
    name_user     VARCHAR(255) GENERATED ALWAYS AS
                  (CASE WHEN removed_at IS NULL AND user_id IS NOT NULL THEN name ELSE NULL END) STORED,
    -- NOTE: there is deliberately NO foreign key on user_id. MySQL 8.0
    -- refuses a foreign key on a column that a generated column's
    -- expression refers to (error 1215), and name_dept / name_user
    -- below both refer to user_id. MariaDB allows it; MySQL 8.0 does
    -- not — that is what kept the live portal from starting. A
    -- user's own columns are deleted explicitly instead, in
    -- core.purge_user_work (their values and hidden-column rows go
    -- with them through the ON DELETE CASCADE keys on column_id).
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    UNIQUE KEY ux_column_name (department_id, name_dept),
    UNIQUE KEY ux_user_column_name (user_id, department_id, name_user)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A record belongs to the department of the person who created it.
CREATE TABLE IF NOT EXISTS records (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    owner_id      INT NOT NULL,
    department_id INT NOT NULL,
    version       INT NOT NULL DEFAULT 1,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at    DATETIME,
    deleted_by    INT,
    FOREIGN KEY (owner_id) REFERENCES users(id),
    FOREIGN KEY (department_id) REFERENCES departments(id),
    FOREIGN KEY (deleted_by) REFERENCES users(id),
    KEY idx_records_owner (owner_id),
    KEY idx_records_dept (department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- The values of a record: one row per filled column (blank = no row).
CREATE TABLE IF NOT EXISTS record_values (
    record_id INT NOT NULL,
    column_id INT NOT NULL,
    value     TEXT,
    PRIMARY KEY (record_id, column_id),
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
    FOREIGN KEY (column_id) REFERENCES columns(id) ON DELETE CASCADE,
    KEY idx_values_column (column_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Departments a record is shared with (their members can view and edit it).
CREATE TABLE IF NOT EXISTS record_shares (
    record_id     INT NOT NULL,
    department_id INT NOT NULL,
    shared_by     INT,
    shared_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    permission    VARCHAR(255) NOT NULL DEFAULT 'edit',
    PRIMARY KEY (record_id, department_id),
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (shared_by) REFERENCES users(id),
    KEY idx_shares_dept (department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A record shared with ONE chosen person (edit or view only), independent of departments.
CREATE TABLE IF NOT EXISTS record_user_shares (
    record_id  INT NOT NULL,
    user_id    INT NOT NULL,
    permission VARCHAR(255) NOT NULL DEFAULT 'edit',
    shared_by  INT,
    shared_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (record_id, user_id),
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (shared_by) REFERENCES users(id),
    KEY idx_user_shares (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Edit history: who changed what and when. Never edited or deleted by the portal.
CREATE TABLE IF NOT EXISTS record_history (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    record_id  INT NOT NULL,
    user_id    INT,
    username   VARCHAR(255),
    full_name  VARCHAR(255),
    action     VARCHAR(255) NOT NULL,
    field      VARCHAR(255),
    old_value  TEXT,
    new_value  TEXT,
    at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
    KEY idx_history_record (record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS repairs (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    record_id  INT NOT NULL,
    date_in    VARCHAR(255),
    problem    TEXT,
    fixed_by   VARCHAR(255),
    cost       VARCHAR(255),
    date_back  VARCHAR(255),
    created_by INT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS attachments (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    record_id     INT NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    stored_name   VARCHAR(255) NOT NULL,
    size          INT NOT NULL,
    uploaded_by   INT,
    scan_status   VARCHAR(255),
    uploaded_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
    FOREIGN KEY (uploaded_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS activity_log (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT,
    username   VARCHAR(255),
    action     VARCHAR(255) NOT NULL,
    details    TEXT,
    ip         VARCHAR(255),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Logged-in browsers. Lets the admin see and end sessions and enforces the idle timeout.
CREATE TABLE IF NOT EXISTS sessions (
    id         VARCHAR(255) PRIMARY KEY,
    user_id    INT NOT NULL,
    ip         VARCHAR(255),
    user_agent TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked    INT NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    KEY idx_sessions_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS login_attempts (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255),
    ip       VARCHAR(255),
    success  INT NOT NULL,
    at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_attempts_user (username, at),
    KEY idx_attempts_ip (ip, at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Comments and suggestions on a record (separate from the edit history).
CREATE TABLE IF NOT EXISTS comments (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    record_id INT NOT NULL,
    user_id   INT NOT NULL,
    kind      VARCHAR(255) NOT NULL DEFAULT 'comment',
    text      TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id),
    KEY idx_comments_record (record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notifications (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    text       TEXT NOT NULL,
    link       VARCHAR(255),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at    DATETIME,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    KEY idx_notif_user (user_id, read_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- LEGACY (kept, not deleted, not rebuilt — see README section 25):
-- Handover of a record to another user (the receiver must accept).
-- There are no pages or routes for transfers, requests or saved_views
-- in this build; their rows are kept so old data is not lost.
CREATE TABLE IF NOT EXISTS transfers (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    record_id   INT NOT NULL,
    from_user   INT NOT NULL,
    to_user     INT NOT NULL,
    status      VARCHAR(255) NOT NULL DEFAULT 'pending',
    note        TEXT,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
    FOREIGN KEY (from_user) REFERENCES users(id),
    FOREIGN KEY (to_user) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Requests that need approval (new item, repair, other).
CREATE TABLE IF NOT EXISTS requests (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    requester_id  INT NOT NULL,
    department_id INT,
    kind          VARCHAR(255) NOT NULL DEFAULT 'other',
    title         VARCHAR(255) NOT NULL,
    details       TEXT,
    status        VARCHAR(255) NOT NULL DEFAULT 'pending',
    decided_by    INT,
    decided_at    DATETIME,
    decision_note TEXT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (requester_id) REFERENCES users(id),
    FOREIGN KEY (department_id) REFERENCES departments(id),
    FOREIGN KEY (decided_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Public QR links: anyone with the link sees ONLY the chosen fields, read-only.
CREATE TABLE IF NOT EXISTS public_links (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    token        VARCHAR(255) NOT NULL UNIQUE,
    owner_id     INT NOT NULL,
    title        VARCHAR(255),
    kind         VARCHAR(255) NOT NULL DEFAULT 'single',
    fields       TEXT,
    enabled      INT NOT NULL DEFAULT 1,
    views        INT NOT NULL DEFAULT 0,
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    regenerated_at DATETIME,
    code_no      INT,
    code_text    VARCHAR(255),
    full_record  INT NOT NULL DEFAULT 0,
    FOREIGN KEY (owner_id) REFERENCES users(id),
    UNIQUE KEY ux_public_code (code_no),
    UNIQUE KEY ux_public_code_text (code_text)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS public_link_records (
    link_id   INT NOT NULL,
    record_id INT NOT NULL,
    PRIMARY KEY (link_id, record_id),
    FOREIGN KEY (link_id) REFERENCES public_links(id) ON DELETE CASCADE,
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Saved filters and sorting ("saved views") of the record lists.
CREATE TABLE IF NOT EXISTS saved_views (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    page       VARCHAR(255) NOT NULL,
    name       VARCHAR(255) NOT NULL,
    query      TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Which reminder notifications were already sent (so nobody gets the same one twice).
-- The date/time VALUE is part of the key: when a meeting is moved, new reminders are sent.
CREATE TABLE IF NOT EXISTS reminder_sent (
    record_id   INT NOT NULL,
    column_id   INT NOT NULL,
    value       VARCHAR(255) NOT NULL,
    offset_days INT NOT NULL,
    sent_on     DATE NOT NULL DEFAULT (CURDATE()),
    PRIMARY KEY (record_id, column_id, value, offset_days),
    FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
    FOREIGN KEY (column_id) REFERENCES columns(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Which daily "upload your signature" morning reminders were already sent
-- (so each user gets it once a day, not on every 5-minute check).
CREATE TABLE IF NOT EXISTS signature_reminder_sent (
    user_id INT NOT NULL,
    sent_on DATE NOT NULL,
    PRIMARY KEY (user_id, sent_on),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Columns a user hid on their own My records Mine tab (build 60). A column
-- a user hid never shows on their Mine tab; a column with no row here
-- shows. The department admin still makes the department's columns — this
-- only records each user's own show/hide choice.
CREATE TABLE IF NOT EXISTS user_hidden_columns (
    user_id   INT NOT NULL,
    column_id INT NOT NULL,
    PRIMARY KEY (user_id, column_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (column_id) REFERENCES columns(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- `key` is a reserved word in MySQL, so the column is `setting_key`.
CREATE TABLE IF NOT EXISTS settings (setting_key VARCHAR(255) PRIMARY KEY, value TEXT)
ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ======================= Department database (tabs inside one department database) =======================
CREATE TABLE IF NOT EXISTS ddb_tabs (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    name          VARCHAR(255) NOT NULL,
    template      VARCHAR(255),
    meeting_notify INT NOT NULL DEFAULT 0,
    position      INT NOT NULL DEFAULT 0,
    created_by    INT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    removed_at    DATETIME,
    deleted_by    INT,
    name_live     VARCHAR(255) GENERATED ALWAYS AS
                  (CASE WHEN removed_at IS NULL THEN name ELSE NULL END) STORED,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (deleted_by) REFERENCES users(id),
    UNIQUE KEY ux_ddb_tab_name (department_id, name_live)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A user a dept admin chose to do everything a dept admin can do in the Department Database.
CREATE TABLE IF NOT EXISTS ddb_delegates (
    department_id INT NOT NULL,
    user_id       INT NOT NULL,
    granted_by    INT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (department_id, user_id),
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (granted_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ddb_columns (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    tab_id        INT,
    name          VARCHAR(255) NOT NULL,
    col_type      VARCHAR(255) NOT NULL CHECK (col_type IN ('text','longtext','number','date','dropdown','yesno','attachment')),
    options       TEXT,
    required      INT NOT NULL DEFAULT 0,
    shown         INT NOT NULL DEFAULT 1,
    has_time      INT NOT NULL DEFAULT 0,
    position      INT NOT NULL DEFAULT 0,
    removed_at    DATETIME,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name_live     VARCHAR(255) GENERATED ALWAYS AS
                  (CASE WHEN removed_at IS NULL THEN name ELSE NULL END) STORED,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (tab_id) REFERENCES ddb_tabs(id) ON DELETE CASCADE,
    UNIQUE KEY ux_ddb_column_name (department_id, tab_id, name_live)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ddb_rows (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    tab_id        INT,
    owner_id      INT NOT NULL,
    version       INT NOT NULL DEFAULT 1,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at    DATETIME,
    deleted_by    INT,
    source_record_id INT,
    public_code   VARCHAR(255),
    public_enabled INT NOT NULL DEFAULT 0,
    public_views  INT NOT NULL DEFAULT 0,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (tab_id) REFERENCES ddb_tabs(id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id) REFERENCES users(id),
    FOREIGN KEY (deleted_by) REFERENCES users(id),
    KEY idx_ddb_rows_dept (department_id, deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ddb_values (
    row_id    INT NOT NULL,
    column_id INT NOT NULL,
    value     TEXT,
    PRIMARY KEY (row_id, column_id),
    FOREIGN KEY (row_id) REFERENCES ddb_rows(id) ON DELETE CASCADE,
    FOREIGN KEY (column_id) REFERENCES ddb_columns(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ddb_history (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    row_id    INT NOT NULL,
    user_id   INT,
    full_name VARCHAR(255),
    action    VARCHAR(255) NOT NULL,
    field     VARCHAR(255),
    old_value TEXT,
    new_value TEXT,
    at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (row_id) REFERENCES ddb_rows(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- What each person may do in the department database: view, own (add + manage own rows),
-- edit (edit every row) or manager (does the department admin's tasks). No row = own.
CREATE TABLE IF NOT EXISTS ddb_meeting_sent (
    row_id      INT NOT NULL,
    column_id   INT NOT NULL,
    value       VARCHAR(255) NOT NULL,
    offset_days INT NOT NULL,
    user_id     INT NOT NULL,
    sent_on     DATE NOT NULL DEFAULT (CURDATE()),
    PRIMARY KEY (row_id, column_id, value, offset_days, user_id),
    FOREIGN KEY (row_id) REFERENCES ddb_rows(id) ON DELETE CASCADE,
    FOREIGN KEY (column_id) REFERENCES ddb_columns(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ddb_perms (
    department_id INT NOT NULL,
    user_id       INT NOT NULL,
    level         VARCHAR(255) NOT NULL DEFAULT 'own',
    PRIMARY KEY (department_id, user_id),
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Row sharing: a whole department, or one specific user, with view or edit permission.
CREATE TABLE IF NOT EXISTS ddb_row_shares (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    row_id        INT NOT NULL,
    department_id INT,
    user_id       INT,
    permission    VARCHAR(255) NOT NULL DEFAULT 'view',
    created_by    INT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (row_id) REFERENCES ddb_rows(id) ON DELETE CASCADE,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tab sharing (build 78): a whole Department Database tab's All rows, shared
-- by its department admin with another department or one specific user, with
-- view or edit permission. A grant is either a department grant
-- (department_id set, user_id NULL) or a user grant (user_id set,
-- department_id NULL). Row sharing above is no longer used.
CREATE TABLE IF NOT EXISTS ddb_tab_shares (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    tab_id        INT NOT NULL,
    department_id INT,
    user_id       INT,
    access        VARCHAR(10) NOT NULL DEFAULT 'view',
    created_by    INT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_tab_dept (tab_id, department_id),
    UNIQUE KEY uq_tab_user (tab_id, user_id),
    FOREIGN KEY (tab_id) REFERENCES ddb_tabs(id) ON DELETE CASCADE,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Special-tab sharing (build 109): a whole special Department Database
-- tab — Client onboarding, Invoices or Request items — shared by the
-- department that owns it with another department or one specific user.
-- View only, never Edit. A grant is either a department grant
-- (department_id set, user_id NULL) or a user grant (user_id set,
-- department_id NULL). The owner is the Sales department for Client
-- onboarding, and the sharing department itself for Invoices and
-- Request items.
CREATE TABLE IF NOT EXISTS special_tab_shares (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    tab_key       VARCHAR(20) NOT NULL,
    owner_dept_id INT NOT NULL,
    department_id INT,
    user_id       INT,
    access        VARCHAR(10) NOT NULL DEFAULT 'view',
    created_by    INT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_special_dept (tab_key, owner_dept_id, department_id),
    UNIQUE KEY uq_special_user (tab_key, owner_dept_id, user_id),
    FOREIGN KEY (owner_dept_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ======================= Invoices (dept-admin templates, employee invoices) =======================
CREATE TABLE IF NOT EXISTS invoice_templates (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    created_by    INT,
    name          VARCHAR(255) NOT NULL,
    kind          VARCHAR(255) NOT NULL DEFAULT 'billing',
    title         VARCHAR(255) NOT NULL DEFAULT 'INVOICE',
    subtitle      VARCHAR(255),
    number_prefix VARCHAR(255) NOT NULL DEFAULT 'BIL',
    next_number   INT NOT NULL DEFAULT 1,
    default_currency VARCHAR(255) NOT NULL DEFAULT 'BDT',
    vat_percent   DOUBLE NOT NULL DEFAULT 0,
    show_tax      INT NOT NULL DEFAULT 1,
    show_amount_in_words INT NOT NULL DEFAULT 1,
    notes         TEXT,
    show_company_logo INT NOT NULL DEFAULT 1,
    show_address  INT NOT NULL DEFAULT 1,
    company_name  VARCHAR(255) NOT NULL DEFAULT '',
    company_address VARCHAR(255) NOT NULL DEFAULT '',
    logo_left     VARCHAR(255),
    logo_right    VARCHAR(255),
    watermark_on  INT NOT NULL DEFAULT 0,
    watermark_text TEXT,
    signatures_json TEXT,
    top_fields_json TEXT,
    item_columns_json TEXT,
    status        VARCHAR(255) NOT NULL DEFAULT 'active',
    shared_from_id INT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id),
    FOREIGN KEY (shared_from_id) REFERENCES invoice_templates(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS invoices (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    tab_id        INT,
    owner_id      INT NOT NULL,
    template_id   INT,
    number        VARCHAR(255),
    title         VARCHAR(255),
    subtitle      VARCHAR(255),
    currency      VARCHAR(255) NOT NULL DEFAULT 'BDT',
    customer_name VARCHAR(255),
    customer_address TEXT,
    reference     VARCHAR(255),
    invoice_date  VARCHAR(255),
    status        VARCHAR(255) NOT NULL DEFAULT 'draft',
    subtotal      DOUBLE NOT NULL DEFAULT 0,
    vat_amount    DOUBLE NOT NULL DEFAULT 0,
    total         DOUBLE NOT NULL DEFAULT 0,
    amount_in_words TEXT,
    notes         TEXT,
    signatures_json TEXT,
    template_snapshot_json TEXT,
    public_code   VARCHAR(255) UNIQUE,
    public_enabled INT NOT NULL DEFAULT 0,
    public_views  INT NOT NULL DEFAULT 0,
    public_show_amounts INT NOT NULL DEFAULT 1,
    public_show_customer INT NOT NULL DEFAULT 1,
    public_show_lines INT NOT NULL DEFAULT 0,
    public_expires VARCHAR(255),
    void_reason   TEXT,
    deleted_at    DATETIME,
    deleted_by    INT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (tab_id) REFERENCES ddb_tabs(id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id) REFERENCES users(id),
    FOREIGN KEY (template_id) REFERENCES invoice_templates(id),
    FOREIGN KEY (deleted_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS invoice_lines (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    invoice_id    INT NOT NULL,
    position      INT NOT NULL DEFAULT 0,
    item_name     VARCHAR(255),
    description   TEXT,
    qty           DOUBLE NOT NULL DEFAULT 1,
    rate          DOUBLE NOT NULL DEFAULT 0,
    amount        DOUBLE NOT NULL DEFAULT 0,
    line_date     VARCHAR(255),
    from_place    VARCHAR(255),
    to_place      VARCHAR(255),
    mode          VARCHAR(255),
    purpose       VARCHAR(255),
    spec          VARCHAR(255),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS invoice_template_shares (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    template_id   INT NOT NULL,
    from_department_id INT NOT NULL,
    to_department_id INT NOT NULL,
    shared_by     INT,
    expires       VARCHAR(255),
    revoked       INT NOT NULL DEFAULT 0,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (template_id) REFERENCES invoice_templates(id) ON DELETE CASCADE,
    FOREIGN KEY (from_department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (to_department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (shared_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS invoice_dept_shares (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    from_department_id INT NOT NULL,
    to_department_id INT NOT NULL,
    shared_by     INT,
    scope         VARCHAR(255) NOT NULL DEFAULT 'invoices',
    expires       VARCHAR(255),
    revoked       INT NOT NULL DEFAULT 0,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (to_department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (shared_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS invoice_steps (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    invoice_id     INT NOT NULL,
    position       INT NOT NULL,
    role           VARCHAR(255) NOT NULL CHECK (role IN ('checked','approved','authorised')),
    user_id        INT,
    status         VARCHAR(255) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    signature_path VARCHAR(255),
    signature_at   DATETIME,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY (invoice_id, position),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id),
    KEY idx_inv_steps (invoice_id, position)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ======================= Item Requests (dept-admin kinds, user requests to HR & Admin) =======================
CREATE TABLE IF NOT EXISTS item_request_kinds (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    created_by    INT,
    name          VARCHAR(255) NOT NULL,
    number_prefix VARCHAR(255) NOT NULL DEFAULT 'REQ',
    next_number   INT NOT NULL DEFAULT 1,
    default_currency VARCHAR(255) NOT NULL DEFAULT 'BDT',
    show_amount_in_words INT NOT NULL DEFAULT 1,
    notes         TEXT,
    show_company_logo INT NOT NULL DEFAULT 1,
    show_address  INT NOT NULL DEFAULT 1,
    company_name  VARCHAR(255) NOT NULL DEFAULT '',
    company_address VARCHAR(255) NOT NULL DEFAULT '',
    logo_left     VARCHAR(255),
    logo_right    VARCHAR(255),
    signatures_json TEXT,
    status        VARCHAR(255) NOT NULL DEFAULT 'active',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS item_requests (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    department_id INT NOT NULL,
    kind_id       INT,
    owner_id      INT NOT NULL,
    recipient_id  INT,
    number        VARCHAR(255),
    currency      VARCHAR(255) NOT NULL DEFAULT 'BDT',
    request_date  VARCHAR(255),
    status        VARCHAR(255) NOT NULL DEFAULT 'pending',
    subtotal      DOUBLE NOT NULL DEFAULT 0,
    total         DOUBLE NOT NULL DEFAULT 0,
    amount_in_words TEXT,
    notes         TEXT,
    signatures_json TEXT,
    kind_snapshot_json TEXT,
    public_code   VARCHAR(255) UNIQUE,
    public_enabled INT NOT NULL DEFAULT 0,
    public_views  INT NOT NULL DEFAULT 0,
    deleted_at    DATETIME,
    deleted_by    INT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (kind_id) REFERENCES item_request_kinds(id),
    FOREIGN KEY (owner_id) REFERENCES users(id),
    FOREIGN KEY (recipient_id) REFERENCES users(id),
    FOREIGN KEY (deleted_by) REFERENCES users(id),
    KEY idx_req_owner (owner_id),
    KEY idx_req_recip (recipient_id),
    KEY idx_req_dept (department_id),
    KEY idx_req_code (public_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS item_request_lines (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    request_id    INT NOT NULL,
    position      INT NOT NULL DEFAULT 0,
    item_name     VARCHAR(255),
    description   TEXT,
    qty           DOUBLE NOT NULL DEFAULT 1,
    rate          DOUBLE NOT NULL DEFAULT 0,
    amount        DOUBLE NOT NULL DEFAULT 0,
    FOREIGN KEY (request_id) REFERENCES item_requests(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS item_request_history (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    request_id INT NOT NULL,
    user_id    INT,
    username   VARCHAR(255),
    full_name  VARCHAR(255),
    action     VARCHAR(255) NOT NULL,
    field      VARCHAR(255),
    old_value  TEXT,
    new_value  TEXT,
    at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (request_id) REFERENCES item_requests(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id),
    KEY idx_req_hist (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS item_request_steps (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    request_id     INT NOT NULL,
    position       INT NOT NULL,
    role           VARCHAR(255) NOT NULL CHECK (role IN ('checked','send_to','approved','authorised')),
    user_id        INT,
    status         VARCHAR(255) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    signature_path VARCHAR(255),
    signature_at   DATETIME,
    created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY (request_id, position),
    FOREIGN KEY (request_id) REFERENCES item_requests(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id),
    KEY idx_req_steps (request_id, position)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ======================= Client onboarding (build 85) =======================
-- One row per new client sent through the onboarding flow: Sales fills three
-- pages (client, contacts, services/SOF), the Sales admin approves, then
-- Revenue Assurance / Transmission / Core / Technical support see it, one SAN
-- report is uploaded, Revenue Assurance sets the activation date and Finance
-- receives the final record. Every user column is ON DELETE SET NULL, so purging
-- a user never blocks and never deletes a client.
CREATE TABLE IF NOT EXISTS client_onboardings (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    department_id      INT NOT NULL,
    owner_id           INT,
    client_name        VARCHAR(255) NOT NULL,
    business_type      VARCHAR(255),
    address            TEXT,
    phone              VARCHAR(255),
    email              VARCHAR(255),
    notes              TEXT,
    account_manager_id INT,
    am_full_name       VARCHAR(255),
    am_designation     VARCHAR(255),
    am_phone           VARCHAR(255),
    am_email           VARCHAR(255),
    status             VARCHAR(255) NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','rejected','approved','forwarded','san_uploaded','completed')),
    reject_reason      TEXT,
    decided_by         INT,
    decided_at         DATETIME,
    san_file           TEXT,
    san_by             INT,
    san_at             DATETIME,
    activation_date    DATE,
    activation_by      INT,
    activation_at      DATETIME,
    deleted_at         DATETIME,
    deleted_by         INT,
    created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (account_manager_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (decided_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (san_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (activation_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (deleted_by) REFERENCES users(id) ON DELETE SET NULL,
    KEY idx_client_status (status),
    KEY idx_client_owner (owner_id),
    KEY idx_client_dept (department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS client_contacts (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    client_id   INT NOT NULL,
    position    INT NOT NULL DEFAULT 0,
    name        VARCHAR(255) NOT NULL,
    designation VARCHAR(255),
    phone       VARCHAR(255),
    email       VARCHAR(255),
    FOREIGN KEY (client_id) REFERENCES client_onboardings(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- The services of a client: one row per SOF (Service Order Form), several allowed.
-- sof_file is the JSON {"stored":..., "original":...} the attachment helpers use.
-- activation_date is the date for THIS SOF (set by Sales when the client is
-- added, changed by Revenue Assurance after the SAN report); the old
-- client-level activation_date on client_onboardings is no longer used.
-- public_code is the SOF's own share code (HRC-#####) for the QR on its PDF.
-- service_type is the short service name the user types (build 102): it is
-- what the Client onboarding tab shows in brackets after each date.
-- service_description is the SOF's description, also typed by the user.
-- status is the SOF's own state (build 102): pending until the flow has run
-- for it, activated once it is live, terminated once its termination has
-- taken effect. termination_date, commercial_impact_date and
-- termination_reason are filled by the account manager when a service ends;
-- the termination only takes effect after the SOF's flow has run again.
CREATE TABLE IF NOT EXISTS client_services (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    client_id  INT NOT NULL,
    position   INT NOT NULL DEFAULT 0,
    sof_number VARCHAR(255) NOT NULL,
    service    VARCHAR(255) NOT NULL,
    service_type VARCHAR(255) NOT NULL DEFAULT '',
    service_description TEXT,
    details    TEXT,
    sof_file   TEXT,
    activation_date DATE,
    termination_date DATE,
    commercial_impact_date DATE,
    termination_reason TEXT,
    status     VARCHAR(32) NOT NULL DEFAULT 'pending',
    public_code VARCHAR(255),
    public_enabled INT NOT NULL DEFAULT 1,
    public_views INT NOT NULL DEFAULT 0,
    san_file   TEXT,
    san_by     INT,
    san_at     DATETIME,
    FOREIGN KEY (client_id) REFERENCES client_onboardings(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A change the account manager made to a SOF on a finished client
-- (build 102): the new values wait here until the Sales admin approves
-- them. service_id is NULL for a brand-new SOF. old_values / new_values
-- are JSON snapshots of the SOF row; status is awaiting, approved or
-- rejected; reason is the Sales admin's reason when rejecting.
CREATE TABLE IF NOT EXISTS client_sof_edits (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    client_id  INT NOT NULL,
    service_id INT,
    editor_id  INT NOT NULL,
    old_values TEXT,
    new_values TEXT NOT NULL,
    status     VARCHAR(32) NOT NULL DEFAULT 'awaiting',
    reason     TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    decided_by INT,
    decided_at DATETIME,
    FOREIGN KEY (client_id) REFERENCES client_onboardings(id) ON DELETE CASCADE,
    FOREIGN KEY (service_id) REFERENCES client_services(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- The Sales & Marketing admin's fields for the three Add Client pages.
-- The fields the client was built with are the defaults (is_default=1,
-- field_key = the fixed column they map to); the admin adds his own
-- (field_key NULL) and can rename any field's column name, change a
-- custom field's type, and set required or not. Structural defaults
-- (client name, contact name, SOF number, service, activation date)
-- stay required and keep their type.
CREATE TABLE IF NOT EXISTS client_form_fields (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    page       INT NOT NULL,
    field_key  VARCHAR(64),
    name       VARCHAR(255) NOT NULL,
    field_type VARCHAR(32) NOT NULL DEFAULT 'text',
    required   INT NOT NULL DEFAULT 0,
    options    TEXT,
    position   INT NOT NULL DEFAULT 0,
    is_default INT NOT NULL DEFAULT 0,
    UNIQUE KEY ux_cff_key (field_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- The values of the admin's custom fields. target_type is 'client'
-- (a page-1 field, target_id = the client), 'contact' (a page-2 field,
-- target_id = the contact row) or 'service' (a page-3 field, target_id =
-- the service row). Default fields keep their fixed columns.
CREATE TABLE IF NOT EXISTS client_field_values (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    client_id   INT NOT NULL,
    target_type VARCHAR(16) NOT NULL DEFAULT 'client',
    target_id   INT NOT NULL,
    field_id    INT NOT NULL,
    value       TEXT,
    FOREIGN KEY (client_id) REFERENCES client_onboardings(id) ON DELETE CASCADE,
    FOREIGN KEY (field_id) REFERENCES client_form_fields(id) ON DELETE CASCADE,
    KEY idx_cfv (client_id, target_type, target_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS client_history (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    client_id INT NOT NULL,
    user_id   INT,
    full_name VARCHAR(255),
    action    VARCHAR(255) NOT NULL,
    detail    TEXT,
    at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES client_onboardings(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    KEY idx_client_hist (client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dashboard settings (2026-11-06): one row per admin, JSON with which
-- dashboard sections that admin wants to see and which chart type (bar/pie)
-- each of the two department charts uses. No row = everything shown, bars.
CREATE TABLE IF NOT EXISTS dashboard_settings (
    user_id       INT NOT NULL PRIMARY KEY,
    settings_json TEXT,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def connect():
    """Open a MySQL connection (see dbapi.py for the wrapper)."""
    return dbapi.connect()


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
    return conn.execute("SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema=DATABASE() AND table_name=?",
                        (name,)).fetchone() is not None


def _columns(conn, table):
    """The column names of a table (MySQL's answer to PRAGMA table_info)."""
    return [r[0] for r in conn.execute(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=? ORDER BY ORDINAL_POSITION",
        (table,))]


def _index_exists(conn, name):
    return conn.execute("SELECT 1 FROM information_schema.statistics "
                        "WHERE table_schema=DATABASE() AND index_name=?",
                        (name,)).fetchone() is not None


def _drop_index(conn, name, table):
    """Drop an index only if it exists (MySQL has no DROP INDEX IF EXISTS)."""
    if _index_exists(conn, name):
        conn.execute(f"DROP INDEX {name} ON {table}")


def _table_sql(conn, table):
    """The CREATE TABLE statement of a table, or None. Used to tell
    whether an old table's CHECK still lacks a value (the rebuild
    migrations below)."""
    row = conn.execute("SHOW CREATE TABLE " + table).fetchone()
    return row[1] if row else None


def _upgrade_repairs_switch(conn):
    """The repair log became a per-department switch. Departments that already have repair
    entries (and the IT department) keep it ON, so nothing disappears; all others start OFF."""
    have = _columns(conn, "departments")
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
    have = _columns(conn, "public_links")
    if "code_no" not in have:
        conn.execute("ALTER TABLE public_links ADD COLUMN code_no INT")
    if "full_record" not in have:
        conn.execute("ALTER TABLE public_links ADD COLUMN full_record INT NOT NULL DEFAULT 0")
    # A plain UNIQUE KEY already allows several NULLs, so the SQLite
    # partial index (WHERE code_text IS NOT NULL) needs no equivalent.
    if not _index_exists(conn, "ux_public_code"):
        conn.execute("CREATE UNIQUE INDEX ux_public_code ON public_links(code_no)")
    if "code_text" not in _columns(conn, "public_links"):
        conn.execute("ALTER TABLE public_links ADD COLUMN code_text VARCHAR(255)")
    if not _index_exists(conn, "ux_public_code_text"):
        conn.execute("CREATE UNIQUE INDEX ux_public_code_text ON public_links(code_text)")
    for _row in conn.execute("SELECT id FROM public_links WHERE code_text IS NULL OR code_text='' ORDER BY id").fetchall():
        _cand = _new_random_code_text(conn)
        if _cand:
            conn.execute("UPDATE public_links SET code_text=? WHERE id=?", (_cand, _row["id"]))
    nxt = conn.execute("SELECT value FROM settings WHERE setting_key='hrc_next'").fetchone()
    n = int(nxt["value"]) if nxt else 0
    for row in conn.execute("SELECT id FROM public_links WHERE code_no IS NULL ORDER BY id").fetchall():
        conn.execute("UPDATE public_links SET code_no=? WHERE id=?", (n, row["id"]))
        n += 1
    conn.execute("INSERT INTO settings(setting_key,value) VALUES ('hrc_next',?) "
                 "ON CONFLICT(setting_key) DO UPDATE SET value=excluded.value", (str(n),))


def _upgrade_ddb_attachment_type(conn):
    """Old ddb_columns tables have CHECK(col_type IN (...)) without 'attachment'.
    On MySQL there is no table rebuild: the column is widened in place.
    (A fresh MySQL database already has 'attachment' in the CHECK from
    SCHEMA, so this is a no-op there.)"""
    sql = _table_sql(conn, "ddb_columns")
    if sql is None or "'attachment'" in sql:
        return
    conn.execute("ALTER TABLE ddb_columns MODIFY COLUMN col_type VARCHAR(255) NOT NULL "
                 "CHECK (col_type IN ('text','longtext','number','date','dropdown','yesno','attachment'))")


def _seed_client_form_fields(conn):
    """The Add Client form's default fields (build 93): the fields the
    client was built with, one per page. The admin adds his own on top
    and renames / toggles required on these; the table is only seeded
    when it is empty, so an admin's changes are never overwritten."""
    if conn.execute("SELECT COUNT(*) FROM client_form_fields").fetchone()[0]:
        return
    _defaults = [
        # field_key, page, name, type, required, position
        ("client_name", 1, "Client name", "text", 1, 0),
        ("business_type", 1, "Business type", "text", 0, 1),
        ("address", 1, "Address", "longtext", 0, 2),
        ("phone", 1, "Phone", "text", 0, 3),
        ("email", 1, "Email", "text", 0, 4),
        ("notes", 1, "Notes", "longtext", 0, 5),
        ("contact_name", 2, "Contact name", "text", 1, 0),
        ("contact_designation", 2, "Designation", "text", 0, 1),
        ("contact_phone", 2, "Phone", "text", 0, 2),
        ("contact_email", 2, "Email", "text", 0, 3),
        ("sof_number", 3, "SOF number", "text", 1, 0),
        ("sof_service", 3, "Service", "text", 1, 1),
        ("sof_details", 3, "Details", "longtext", 0, 2),
        ("sof_activation_date", 3, "Activation date", "date", 1, 3),
        # Build 102: the service description — it must be filled. The
        # Service type box is gone in build 109 (Service and Service type
        # meant the same thing); the short name is the Service itself.
        ("sof_service_description", 3, "Service description", "longtext", 1, 5),
    ]
    for _key, _page, _name, _type, _req, _pos in _defaults:
        conn.execute("INSERT INTO client_form_fields(page,field_key,name,field_type,required,position,is_default)"
                     " VALUES (?,?,?,?,?,?,1)", (_page, _key, _name, _type, _req, _pos))


def _upgrade_sof_type_fields(conn):
    """Build 102 adds the Service description field to the Add Client
    form. The seed above only runs when the fields table is empty, so a
    live database that already has fields needs this row added here (it
    is structural, so the admin cannot remove it). Build 109 removes the
    Service type box (Service and Service type meant the same thing), so
    the Service type field row is deleted here when it is still present
    — the form no longer asks for it, and the short name is the Service
    itself."""
    have = {r[0] for r in conn.execute("SELECT field_key FROM client_form_fields").fetchall()}
    if "sof_service_description" not in have:
        conn.execute("INSERT INTO client_form_fields(page,field_key,name,field_type,required,position,is_default)"
                     " VALUES (3,'sof_service_description','Service description','longtext',1,5,1)")
    if "sof_service_type" in have:
        conn.execute("DELETE FROM client_form_fields WHERE field_key='sof_service_type'")


def _upgrade_sof_status(conn):
    """Build 102 gives every SOF its own status and the new type /
    description / termination columns. A SOF that already has a type
    keeps it; one without takes the service name as its short name. A
    SOF is activated when its client is already finished (completed)
    and it has an activation date; every other SOF starts pending."""
    for _col, _ddl in (("service_type", "VARCHAR(255) NOT NULL DEFAULT ''"),
                       ("service_description", "TEXT"),
                       ("termination_date", "DATE"),
                       ("commercial_impact_date", "DATE"),
                       ("termination_reason", "TEXT"),
                       ("status", "VARCHAR(32) NOT NULL DEFAULT 'pending'")):
        _ensure_column(conn, "client_services", _col, _ddl)
    conn.execute("UPDATE client_services SET service_type=service "
                 "WHERE service_type IS NULL OR service_type=''")
    conn.execute("UPDATE client_services s JOIN client_onboardings c ON c.id=s.client_id "
                 "SET s.status='activated' WHERE c.status='completed' AND s.activation_date IS NOT NULL "
                 "AND (s.status IS NULL OR s.status='' OR s.status='pending')")
    conn.execute("UPDATE client_services SET status='terminated' "
                 "WHERE termination_date IS NOT NULL AND status<>'terminated'")


def _upgrade_sof_dates(conn):
    """Build 93 moves the activation date from the client to each SOF.
    A client that already has a client-level date keeps it on every SOF
    that has none yet (so a completed client like CL-0003 keeps its
    date); SOFs that already have a date are untouched."""
    if "activation_date" not in _columns(conn, "client_services"):
        return
    rows = conn.execute("SELECT id, activation_date FROM client_onboardings"
                        " WHERE activation_date IS NOT NULL").fetchall()
    for _c in rows:
        conn.execute("UPDATE client_services SET activation_date=?"
                     " WHERE client_id=? AND activation_date IS NULL",
                     (_c["activation_date"], _c["id"]))


def _upgrade_sof_san(conn):
    """Build 105 gives every SOF its own SAN report (build 105). A client
    that already has the one client-level SAN report keeps it: the file is
    copied onto each of its SOFs that has none yet, so nothing changes for
    clients like CL-0003. The client-level columns stay in the database
    (history); the upload itself is per SOF from here on."""
    if "san_file" not in _columns(conn, "client_services"):
        return
    if "san_file" not in _columns(conn, "client_onboardings"):
        return
    rows = conn.execute("SELECT id, san_file, san_by, san_at FROM client_onboardings"
                        " WHERE san_file IS NOT NULL").fetchall()
    for _c in rows:
        conn.execute("UPDATE client_services SET san_file=?, san_by=?, san_at=?"
                     " WHERE client_id=? AND san_file IS NULL",
                     (_c["san_file"], _c["san_by"], _c["san_at"], _c["id"]))


def _upgrade_client_status(conn):
    """Build 89: the client flow gained the "forwarded" status (Revenue
    Assurance forwards an approved client to Transmission, Core and
    Technical support). Old client_onboardings tables have a CHECK without
    it. Widening it in place takes DROP CHECK + ADD CHECK: MODIFY COLUMN
    only ADDS a second CHECK and the old one would still block 'forwarded'
    (error 3819). The new CHECK is a superset of the old one, so no
    existing row can violate it. (A fresh database already has 'forwarded'
    in the CHECK from SCHEMA, so this is a no-op there.)"""
    if not _table_exists(conn, "client_onboardings"):
        return
    try:
        rows = conn.execute(
            "SELECT tc.CONSTRAINT_NAME AS cname, cc.CHECK_CLAUSE AS clause "
            "FROM information_schema.TABLE_CONSTRAINTS tc "
            "JOIN information_schema.CHECK_CONSTRAINTS cc "
            "  ON cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME AND cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA "
            "WHERE tc.TABLE_SCHEMA = DATABASE() AND tc.TABLE_NAME = 'client_onboardings' "
            "AND tc.CONSTRAINT_TYPE = 'CHECK'").fetchall()
    except Exception:
        return
    widened = False
    for r in rows:
        # NOTE (build 93): match the bare word, not "'forwarded'". MySQL
        # stores the clause with the literals escaped (_utf8mb4\'forwarded\'),
        # so the quoted form never matches and the widened CHECK was dropped
        # and re-added on every upgrade. Worse, that second DROP on the same
        # table inside one uncommitted init_db transaction can deadlock with
        # InnoDB's dict_stats thread (it queues a SHARED lock behind the first
        # DROP's TRANSACTION lock, and the second DROP then queues behind it).
        if "forwarded" in (r["clause"] or ""):
            widened = True
        else:
            conn.execute("ALTER TABLE client_onboardings DROP CHECK `" + r["cname"] + "`")
    if not widened:
        conn.execute("ALTER TABLE client_onboardings ADD CHECK (status IN "
                     "('pending','rejected','approved','forwarded','san_uploaded','completed'))")


def _upgrade_columns_user_columns(conn):
    """Old columns tables have no user_id and a CHECK(col_type IN (...))
    without 'attachment' (build 61: users add their own Mine-tab columns,
    including an Attachment type). On MySQL the column is added in place
    and the CHECK is widened in place — no table rebuild, so no data is
    ever at risk. There is deliberately NO foreign key on user_id:
    MySQL 8.0 refuses an FK on a column that a generated column's
    expression refers to (error 1215); the per-user and per-department
    unique indexes live in SCHEMA as generated columns, so they need no
    ensuring here. (A fresh MySQL database already has all of this.)"""
    if not _table_exists(conn, "columns"):
        return
    if "user_id" not in _columns(conn, "columns"):
        conn.execute("ALTER TABLE columns ADD COLUMN user_id INT")
    sql = _table_sql(conn, "columns")
    if sql is not None and "'attachment'" not in sql:
        conn.execute("ALTER TABLE columns MODIFY COLUMN col_type VARCHAR(255) NOT NULL "
                     "CHECK (col_type IN ('text','longtext','number','date','dropdown','yesno','attachment'))")


def _drop_application_tables(conn):
    """Build 83: the Application Letters feature is removed. Drop its six
    tables when they exist, children first so the foreign keys do not
    block the drop. A database backup taken before applying the build is
    the only way back."""
    for _t in ("application_steps", "application_history",
               "application_date_changes", "applications",
               "application_kinds", "leave_setup"):
        conn.execute(f"DROP TABLE IF EXISTS {_t}")



def _drop_sales_pipeline_tab(conn):
    """Build 84: the Sales Pipeline tab is removed from the Sales &
    Marketing department, with all its rows. Delete every tab named
    'Sales Pipeline' in that department (live or in the Recycle Bin),
    children first so the foreign keys do not block the delete. A
    database backup taken before applying the build is the only way
    back. Tabs another department made from the template are left
    alone: they are ordinary tabs now."""
    row = conn.execute("SELECT id FROM departments WHERE LOWER(name)='sales & marketing'").fetchone()
    if row is None:
        row = conn.execute("SELECT id FROM departments WHERE LOWER(name) LIKE '%sales%' "
                           "AND LOWER(name) LIKE '%marketing%' ORDER BY id LIMIT 1").fetchone()
    if row is None:
        return
    tabs = conn.execute("SELECT id FROM ddb_tabs WHERE department_id=? AND LOWER(name)='sales pipeline'",
                        (row[0],)).fetchall()
    for (tab_id,) in tabs:
        row_ids = [r[0] for r in conn.execute("SELECT id FROM ddb_rows WHERE tab_id=?", (tab_id,)).fetchall()]
        for rid in row_ids:
            conn.execute("DELETE FROM ddb_values WHERE row_id=?", (rid,))
            conn.execute("DELETE FROM ddb_history WHERE row_id=?", (rid,))
            conn.execute("DELETE FROM ddb_meeting_sent WHERE row_id=?", (rid,))
        conn.execute("DELETE FROM ddb_rows WHERE tab_id=?", (tab_id,))
        conn.execute("DELETE FROM ddb_columns WHERE tab_id=?", (tab_id,))
        conn.execute("DELETE FROM ddb_tab_shares WHERE tab_id=?", (tab_id,))
        conn.execute("DELETE FROM ddb_tabs WHERE id=?", (tab_id,))


def _upgrade_remove_row_shares(conn):
    """Row sharing is gone (build 78): a normal user can no longer share one
    Department Database row with anyone, and only the department admin
    manages sharing, for a whole tab. Any row share a user already made
    disappears, so delete them all. Safe to run on every startup: after the
    first run the table is empty and the DELETE removes nothing."""
    conn.execute("DELETE FROM ddb_row_shares")


def _upgrade_invoice_tax_tick(conn):
    """Per-template tax tick (2026-11-05): invoice_templates.show_tax decides
    whether an invoice made from the template offers tax at all. Added only
    once: existing templates are backfilled from their VAT % (a template with
    a VAT % above 0 keeps tax on, the 0 % starters keep it off), and later
    admin changes to the tick are never overwritten by this upgrade."""
    have = _columns(conn, "invoice_templates")
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
    have = _columns(conn, "invoice_templates")
    if "company_name" not in have:
        conn.execute("ALTER TABLE invoice_templates ADD COLUMN company_name VARCHAR(255) NOT NULL DEFAULT ''")
    if "company_address" not in have:
        conn.execute("ALTER TABLE invoice_templates ADD COLUMN company_address VARCHAR(255) NOT NULL DEFAULT ''")


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
    _ensure_column(conn, "ddb_rows", "public_code", "VARCHAR(255)")  # public QR share code (2026-11-09)
    _ensure_column(conn, "ddb_rows", "public_enabled", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "ddb_rows", "public_views", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "ddb_rows", "deleted_by", "INTEGER REFERENCES users(id)")  # who deleted the row, shown in the Recycle Bin (2026-11-10)
    _ensure_column(conn, "ddb_tabs", "deleted_by", "INTEGER REFERENCES users(id)")  # who deleted the tab, shown in the Recycle Bin Others tab (2026-11-16)
    _ensure_column(conn, "invoices", "deleted_at", "DATETIME")  # soft delete, shown in the Recycle Bin (2026-11-14)
    _ensure_column(conn, "invoices", "deleted_by", "INTEGER REFERENCES users(id)")
    _ensure_column(conn, "item_requests", "deleted_at", "DATETIME")  # soft delete, shown in the Recycle Bin (2026-11-14)
    _ensure_column(conn, "item_requests", "deleted_by", "INTEGER REFERENCES users(id)")
    _ensure_column(conn, "item_request_lines", "item_name", "VARCHAR(255)")  # item name per line (2026-11-09)
    # Per-tab column unique index (an old index was department-wide).
    # On MySQL the index is on the generated name_live column (see
    # SCHEMA); an index that does not cover tab_id is the old one, so
    # it is dropped and the per-tab one is created.
    _idx_cols = [r[0] for r in conn.execute(
        "SELECT COLUMN_NAME FROM information_schema.statistics "
        "WHERE table_schema=DATABASE() AND table_name='ddb_columns' "
        "AND index_name='ux_ddb_column_name' ORDER BY SEQ_IN_INDEX")]
    if _idx_cols and "tab_id" not in _idx_cols:
        _drop_index(conn, "ux_ddb_column_name", "ddb_columns")
        conn.execute("CREATE UNIQUE INDEX ux_ddb_column_name "
                     "ON ddb_columns(department_id, tab_id, name_live)")
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
    """Add a column to an older table if it is missing (keeps existing data).
    The ddl may name a foreign key (``INTEGER REFERENCES users(id)``);
    MySQL ignores an inline REFERENCES, so it is stripped here and the
    foreign key is added as its own constraint."""
    if column in _columns(conn, table):
        return
    import re as _re
    m = _re.search(r"REFERENCES\s+(\w+)\s*\((\w+)\)\s*(ON DELETE CASCADE)?", ddl)
    col_ddl = _re.sub(r"\s*REFERENCES\s+\w+\s*\(\w+\)\s*(ON DELETE CASCADE)?", "", ddl)
    col_ddl = col_ddl.replace("INTEGER", "INT")
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_ddl}")
    if m:
        conn.execute(f"ALTER TABLE {table} ADD FOREIGN KEY ({column}) "
                     f"REFERENCES {m.group(1)}({m.group(2)}) {m.group(3) or ''}")


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
    dbapi.ensure_database()   # create the database itself on the very first start
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "departments", "attachments_enabled", "INT NOT NULL DEFAULT 0")
        _ensure_column(conn, "departments", "attachment_max_mb", "INT NOT NULL DEFAULT 10")
        _ensure_column(conn, "users", "created_by", "INT REFERENCES users(id)")  # who created the account (2026-11-05)
        _ensure_column(conn, "users", "designation", "VARCHAR(255)")  # job title, for the owner signature (2026-11-10)
        _ensure_column(conn, "users", "email", "VARCHAR(255)")  # the user's own mail address, set in My settings (2026-11-16)
        _ensure_column(conn, "users", "phone", "VARCHAR(255)")  # the user's own phone, set at first login (2026-11-19)
        _ensure_column(conn, "client_onboardings", "am_full_name", "VARCHAR(255)")  # the account manager's information for THIS client only (2026-11-19)
        _ensure_column(conn, "client_onboardings", "am_designation", "VARCHAR(255)")
        _ensure_column(conn, "client_onboardings", "am_phone", "VARCHAR(255)")
        _ensure_column(conn, "client_onboardings", "am_email", "VARCHAR(255)")
        _ensure_column(conn, "client_onboardings", "deleted_at", "DATETIME")  # soft delete to the Recycle Bin (2026-11-23)
        _ensure_column(conn, "client_onboardings", "deleted_by", "INT")
        _ensure_column(conn, "client_services", "activation_date", "DATE")  # the activation date of THIS SOF (2026-11-19)
        _ensure_column(conn, "client_services", "public_code", "VARCHAR(255)")  # the SOF's own share code HRC-##### for the QR on its PDF
        _ensure_column(conn, "client_services", "public_enabled", "INT NOT NULL DEFAULT 1")
        _ensure_column(conn, "client_services", "public_views", "INT NOT NULL DEFAULT 0")
        _ensure_column(conn, "client_services", "san_file", "TEXT")  # this SOF's own SAN report (2026-11-23)
        _ensure_column(conn, "client_services", "san_by", "INT")
        _ensure_column(conn, "client_services", "san_at", "DATETIME")
        _seed_client_form_fields(conn)
        _upgrade_sof_type_fields(conn)
        _upgrade_sof_status(conn)
        _upgrade_sof_dates(conn)
        _upgrade_sof_san(conn)
        _ensure_column(conn, "users", "is_dept_admin", "INT NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "can_ddb_attachment", "INT NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "can_portal_admin", "INT NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "is_deleted", "INT NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "deleted_at", "DATETIME")
        _ensure_column(conn, "users", "deleted_by", "INT REFERENCES users(id)")
        _ensure_column(conn, "users", "bin_purged", "INT NOT NULL DEFAULT 0")
        _ensure_column(conn, "users", "approval_status", "VARCHAR(255) NOT NULL DEFAULT 'approved'")
        _ensure_column(conn, "users", "theme", "VARCHAR(255) NOT NULL DEFAULT 'auto'")
        _ensure_column(conn, "users", "warn_days", "INT NOT NULL DEFAULT 3")
        _ensure_column(conn, "users", "signature_path", "VARCHAR(255)")  # the user's own signature (PNG, from My settings) for "Use my signature" (2026-11-14)
        _ensure_column(conn, "columns", "has_time", "INT NOT NULL DEFAULT 0")
        _ensure_column(conn, "record_shares", "permission", "VARCHAR(255) NOT NULL DEFAULT 'edit'")   # old shares stay 'edit'
        _upgrade_repairs_switch(conn)
        _upgrade_public_codes(conn)
        _upgrade_ddb_attachment_type(conn)
        _upgrade_columns_user_columns(conn)
        _upgrade_client_status(conn)
        _upgrade_ddb_tabs(conn)
        _upgrade_remove_row_shares(conn)
        _upgrade_invoice_tax_tick(conn)
        _upgrade_invoice_header(conn)
        _drop_application_tables(conn)
        _drop_sales_pipeline_tab(conn)
        _drop_index(conn, "ux_column_reminder", "columns")   # several reminder columns are allowed now
        _ensure_column(conn, "activity_log", "ip", "VARCHAR(255)")
        _ensure_column(conn, "attachments", "scan_status", "VARCHAR(255)")
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
    row = db.execute("SELECT value FROM settings WHERE setting_key=?", (key,)).fetchone()
    return row["value"] if row else default


def setting_set(db, key, value):
    db.execute("INSERT INTO settings(setting_key,value) VALUES (?,?) "
               "ON CONFLICT(setting_key) DO UPDATE SET value=excluded.value", (key, value))
