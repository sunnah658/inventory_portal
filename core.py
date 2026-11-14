"""
core.py - the business logic of the portal (no web pages here).

Used by: routes_records.py, routes_admin.py, import_users.py, models.py
Uses:    config.py, models.py, templates_data.py, utils.py

What lives here: record columns, permission checks, reading/saving record values,
edit history, recycle bin, department creation and the CSV builder.
"""
import math
import re
import os
import secrets
import shutil
from datetime import date, datetime, timedelta

import config
from models import log
from templates_data import TEMPLATES
from utils import is_portal_admin, is_true_admin, like_pattern

COLUMN_TYPES = [("text", "Text"), ("longtext", "Long text"), ("number", "Number"),
                ("date", "Date"), ("dropdown", "Dropdown list"), ("yesno", "Yes / No")]
TYPE_LABEL = dict(COLUMN_TYPES)
# Department-database columns only: attachment is NOT a record column type.
DDB_COLUMN_TYPES = COLUMN_TYPES + [("attachment", "Attachment (file)")]
DDB_TYPE_LABEL = dict(DDB_COLUMN_TYPES)


# ---------------------------------------------------------------- columns
def col_weight(col_type):
    """Print width weight for one column: long text gets the most room."""
    return 2.0 if col_type == "longtext" else 1.5 if col_type == "text" else 1.0


def print_col_widths(weights):
    """Turn a list of column weights into print width percentages (the print
    table uses a fixed layout, so the percentages decide the columns)."""
    total = sum(weights) or 1.0
    return [round(w / total * 100, 1) for w in weights]


def get_columns(db, dept_id, only_shown=True):
    """Active (not removed) columns of a department, in display order."""
    sql = "SELECT * FROM columns WHERE department_id=? AND removed_at IS NULL"
    if only_shown:
        sql += " AND shown=1"
    return db.execute(sql + " ORDER BY position, id", (dept_id,)).fetchall()


def options_of(col):
    """Dropdown choices of a column as a list."""
    return [o.strip() for o in (col["options"] or "").split("\n") if o.strip()]


def create_department_columns(db, dept_id, template_key, selected=None):
    """Insert the starter columns of a template (selected = list of positions to keep)."""
    for i, spec in enumerate(TEMPLATES.get(template_key, [])):
        name, ctype, opts, reminder = spec[:4]
        has_time = spec[4] if len(spec) > 4 else False       # optional 5th item: date + time
        if selected is not None and i not in selected:
            continue
        db.execute("INSERT INTO columns(department_id,name,col_type,options,position,is_reminder,has_time)"
                   " VALUES (?,?,?,?,?,?,?)",
                   (dept_id, name, ctype, "\n".join(opts) if opts else None, i,
                    1 if reminder else 0, 1 if has_time else 0))


def create_department(db, name, template_key=None, selected=None):
    """Create a department (and its starter columns). Raises sqlite3.IntegrityError if it exists."""
    dept_id = db.execute("INSERT INTO departments(name,repairs_enabled) VALUES (?,?)",
                         (name, 1 if template_key == "IT" else 0)).lastrowid   # only the IT starter has a repair log
    create_department_columns(db, dept_id, template_key, selected)
    # Every department has a Custom Application kind by default (2026-11-14).
    db.execute("INSERT INTO application_kinds(department_id,name,number_prefix,next_number,is_custom) "
               "VALUES (?,?,?,1,1)", (dept_id, "Custom Application", "CA"))
    return dept_id


# ---------------------------------------------------------------- records: reading
def rec_select(extra=""):
    """Base SELECT for records with owner and department names."""
    return ("SELECT r.*, u.full_name AS owner_name, u.username AS owner_username, "
            "u.is_active AS owner_is_active, u.is_deleted AS owner_is_deleted, "
            "d.name AS department_name, d.attachments_enabled, d.attachment_max_mb, d.repairs_enabled" + extra +
            " FROM records r JOIN users u ON u.id=r.owner_id "
            "JOIN departments d ON d.id=r.department_id")


def get_record(db, rid):
    return db.execute(rec_select() + " WHERE r.id=?", (rid,)).fetchone()


def viewable_departments(db, user):
    """Departments this user may VIEW (not edit) besides their own."""
    return [r[0] for r in db.execute(
        "SELECT department_id FROM user_view_departments WHERE user_id=?", (user["id"],))]


def share_permissions(db, user, rec):
    """The permissions ('edit' / 'view') that sharing gives this user on this record:
    through his department and through a share made to him personally."""
    perms = {r[0] for r in db.execute(
        "SELECT permission FROM record_shares WHERE record_id=? AND department_id=?",
        (rec["id"], user["department_id"]))}
    perms |= {r[0] for r in db.execute(
        "SELECT permission FROM record_user_shares WHERE record_id=? AND user_id=?",
        (rec["id"], user["id"]))}
    return perms


def access_level(db, user, rec):
    """What this user is to this record:
    admin / owner  - may edit and manage (share, delete)
    shared         - the record was shared with him (or his department) with EDIT
    shared_view    - the record was shared with him (or his department) as VIEW ONLY
    supervisor     - department admin of the record's department: view and suggest only
    viewer         - allowed to view that department: view and suggest only
    None           - no access
    Edit rights win: one edit share is enough even if another share is view only.
    """
    if is_portal_admin(user):
        return "admin"
    if rec["owner_id"] == user["id"]:
        return "owner"
    perms = share_permissions(db, user, rec)
    if "edit" in perms:
        return "shared"
    if perms:
        return "shared_view"
    if user["is_dept_admin"] and rec["department_id"] == user["department_id"]:
        return "supervisor"
    if rec["department_id"] in viewable_departments(db, user):
        return "viewer"
    return None


EDIT_LEVELS = ("admin", "owner", "shared")
MANAGE_LEVELS = ("admin", "owner")
VIEW_ONLY_LEVELS = ("shared_view", "supervisor", "viewer")     # may read and write suggestions
PERMISSIONS = (("edit", "Can edit"), ("view", "View only"))
PERM_WORDS = {"edit": "can edit", "view": "view only"}


def clean_permission(value):
    """Only 'edit' or 'view' are valid; anything else becomes the safe choice 'view'."""
    return value if value in ("edit", "view") else "view"


def visible_clause(db, user):
    """SQL (and params) for every record this user is allowed to see."""
    if is_portal_admin(user):
        return "1=1", []
    parts = ["r.owner_id=?",
             "EXISTS (SELECT 1 FROM record_shares s WHERE s.record_id=r.id AND s.department_id=?)",
             "EXISTS (SELECT 1 FROM record_user_shares us WHERE us.record_id=r.id AND us.user_id=?)"]
    params = [user["id"], user["department_id"], user["id"]]
    if user["is_dept_admin"]:
        parts.append("r.department_id=?")
        params.append(user["department_id"])
    granted = viewable_departments(db, user)
    if granted:
        parts.append("r.department_id IN (%s)" % ",".join("?" * len(granted)))
        params += granted
    return "(" + " OR ".join(parts) + ")", params


def values_for(db, record_ids):
    """{record_id: {column_id: value}} for many records at once."""
    out = {rid: {} for rid in record_ids}
    ids = list(record_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in db.execute(f"SELECT record_id,column_id,value FROM record_values "
                            f"WHERE record_id IN ({q})", chunk):
            out[r["record_id"]][r["column_id"]] = r["value"]
    return out


def shares_for(db, record_ids):
    """{record_id: [labels]} for many records at once: the departments and the people a record
    is shared with, e.g. 'Sales' / 'Rahim (person, view only)'."""
    out = {rid: [] for rid in record_ids}
    ids = list(record_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in db.execute(f"SELECT s.record_id, d.name, s.permission FROM record_shares s "
                            f"JOIN departments d ON d.id=s.department_id "
                            f"WHERE s.record_id IN ({q}) ORDER BY d.name", chunk):
            out[r["record_id"]].append(r["name"] + (" (view only)" if r["permission"] == "view" else ""))
        for r in db.execute(f"SELECT s.record_id, u.full_name, s.permission FROM record_user_shares s "
                            f"JOIN users u ON u.id=s.user_id "
                            f"WHERE s.record_id IN ({q}) ORDER BY u.full_name", chunk):
            out[r["record_id"]].append(f"{r['full_name']} (person" + (", view only)" if r["permission"] == "view" else ")"))
    return out


def search_clause(q):
    """SQL for a search over all values of a record."""
    if not q:
        return "", []
    return (" AND EXISTS (SELECT 1 FROM record_values v WHERE v.record_id=r.id "
            "AND v.value LIKE ? ESCAPE '\\')", [like_pattern(q)])


def summary_of(columns, vals, n=2):
    """Short title of a record: its first filled short values."""
    parts = [vals.get(c["id"]) for c in columns if c["col_type"] != "longtext" and vals.get(c["id"])]
    return " · ".join(parts[:n]) or "(empty record)"


def table_context(db, rows, user=None):
    """Group records by department so each group is shown with its own columns."""
    ids = [r["id"] for r in rows]
    cols, groups, index = {}, [], {}
    for r in rows:
        d = r["department_id"]
        if d not in cols:
            cols[d] = get_columns(db, d)
        if d not in index:
            index[d] = len(groups)
            groups.append({"dept_id": d, "dept_name": r["department_name"],
                           "columns": cols[d], "rows": [],
                           # Print widths for this group's columns plus the
                           # trailing Owner / Shared-with column (weight 1).
                           "widths": print_col_widths(
                               [col_weight(c["col_type"]) for c in cols[d]] + [1.0])})
        groups[index[d]]["rows"].append(r)
    return {"groups": groups, "vmap": values_for(db, ids), "shares": shares_for(db, ids),
            "multi": len(groups) > 1,
            "levels": {r["id"]: access_level(db, user, r) for r in rows} if user else {}}


# ---------------------------------------------------------------- records: writing
def parse_form(columns, form, existing=None):
    """Read and check the record form. Returns ({column_id: value or None}, [errors])."""
    existing = existing or {}
    values, errors = {}, []
    for c in columns:
        if c["col_type"] == "attachment":
            # file is handled by routes_deptdb (upload / keep / remove); text form has nothing for it
            values[c["id"]] = existing.get(c["id"])
            continue
        raw = (form.get(f"c{c['id']}") or "").strip()
        label, ctype = c["name"], c["col_type"]
        if raw:
            if ctype == "number":
                raw = raw.replace(",", "")
                try:
                    if not math.isfinite(float(raw)):
                        raise ValueError
                except ValueError:
                    errors.append(f"{label} must be a number.")
            elif ctype == "date":
                try:
                    datetime.strptime(raw, "%Y-%m-%d")
                except ValueError:
                    errors.append(f"{label} must be a valid date.")
                else:
                    clock = (form.get(f"c{c['id']}_time") or "").strip()
                    if c["has_time"] and clock:                   # keep the time next to the date
                        try:
                            clock = datetime.strptime(clock, "%H:%M").strftime("%H:%M")
                            raw = f"{raw} {clock}"
                        except ValueError:
                            errors.append(f"{label}: the time must look like 14:30.")
            elif ctype == "dropdown":
                if raw not in options_of(c) and raw != existing.get(c["id"]):
                    errors.append(f"{label}: choose a value from the list.")
            elif ctype == "yesno" and raw not in ("Yes", "No"):
                errors.append(f"{label}: choose Yes or No.")
            limit = 2000 if ctype == "longtext" else 200
            if len(raw) > limit:
                errors.append(f"{label} is too long (maximum {limit} characters).")
        elif c["required"]:
            errors.append(f"{label} is required.")
        if (not raw and ctype == "date" and c["has_time"]
                and (form.get(f"c{c['id']}_time") or "").strip()):
            errors.append(f"{label}: choose a date together with the time.")
        values[c["id"]] = raw or None
    if not errors and not any(values.values()):
        errors.append("Fill in at least one field before saving.")
    return values, errors


def add_history(db, rid, user, action, field=None, old=None, new=None):
    """One line in the edit history of a record (nobody can edit these lines)."""
    db.execute("INSERT INTO record_history(record_id,user_id,username,full_name,action,"
               "field,old_value,new_value) VALUES (?,?,?,?,?,?,?,?)",
               (rid, user["id"] if user else None, user["username"] if user else None,
                user["full_name"] if user else None, action, field, old, new))


def create_record(db, user, dept_id, values):
    rid = db.execute("INSERT INTO records(owner_id,department_id) VALUES (?,?)",
                     (user["id"], dept_id)).lastrowid
    for cid, val in values.items():
        if val is not None:
            db.execute("INSERT INTO record_values(record_id,column_id,value) VALUES (?,?,?)",
                       (rid, cid, val))
    add_history(db, rid, user, "created")
    return rid


def update_record(db, user, rec, columns, new_values, version):
    """Save changes. Returns 'ok', 'nochange' or 'conflict' (someone saved first)."""
    old = values_for(db, [rec["id"]])[rec["id"]]
    changes = [(c, old.get(c["id"]), new_values[c["id"]]) for c in columns
               if (old.get(c["id"]) or None) != new_values[c["id"]]]
    if not changes:
        return "nochange"
    # The version check is the protection against two people saving at the same time.
    done = db.execute("UPDATE records SET version=version+1, updated_at=datetime('now','localtime') "
                      "WHERE id=? AND version=? AND deleted_at IS NULL", (rec["id"], version)).rowcount
    if done == 0:
        db.rollback()
        return "conflict"
    for col, before, after in changes:
        if after is None:
            db.execute("DELETE FROM record_values WHERE record_id=? AND column_id=?",
                       (rec["id"], col["id"]))
        else:
            db.execute("INSERT INTO record_values(record_id,column_id,value) VALUES (?,?,?) "
                       "ON CONFLICT(record_id,column_id) DO UPDATE SET value=excluded.value",
                       (rec["id"], col["id"], after))
        add_history(db, rec["id"], user, "edit", col["name"], before, after)
    return "ok"


# ---------------------------------------------------------------- recycle bin
def soft_delete(db, user, rec):
    db.execute("UPDATE records SET deleted_at=datetime('now','localtime'), deleted_by=? WHERE id=?",
               (user["id"], rec["id"]))
    add_history(db, rec["id"], user, "deleted")


def restore(db, user, rec):
    db.execute("UPDATE records SET deleted_at=NULL, deleted_by=NULL, version=version+1 WHERE id=?",
               (rec["id"],))
    add_history(db, rec["id"], user, "restored")


def purge_record(db, rid):
    """Erase a record for good, including its attachment files."""
    shutil.rmtree(os.path.join(config.UPLOAD_DIR, str(rid)), ignore_errors=True)
    db.execute("DELETE FROM records WHERE id=?", (rid,))      # children are deleted by CASCADE


def _ddb_attachment_files(db, rid):
    """Stored attachment file names of one Department Database row."""
    out = []
    for _v in db.execute("SELECT v.value FROM ddb_values v JOIN ddb_columns c ON c.id=v.column_id "
                         "WHERE v.row_id=? AND c.col_type='attachment'", (rid,)):
        try:
            import json as _json
            _info = _json.loads(_v[0] or "")
            if isinstance(_info, dict) and _info.get("stored"):
                out.append(_info["stored"])
        except Exception:
            pass
    return out


def purge_ddb_row(db, rid):
    """Erase a Department Database row for good, including its attachment files."""
    for stored in _ddb_attachment_files(db, rid):
        try:
            os.remove(os.path.join(config.UPLOAD_DIR, "ddb_attachments", stored))
        except Exception:
            pass
    db.execute("DELETE FROM ddb_rows WHERE id=?", (rid,))      # values/history/shares are deleted by CASCADE


def purge_application(db, aid):
    """Erase an application letter for good, including its uploaded signature files (every step's signature, not only the checker's and the approver's)."""
    row = db.execute("SELECT signature_path, checker_signature_path FROM applications WHERE id=?", (aid,)).fetchone()
    _names = []
    if row:
        _names += [row["signature_path"], row["checker_signature_path"]]
    _names += [r[0] for r in db.execute("SELECT signature_path FROM application_steps WHERE application_id=?", (aid,))]
    for _name in _names:
        if _name:
            try:
                os.remove(os.path.join(config.UPLOAD_DIR, "app_signatures", os.path.basename(_name)))
            except Exception:
                pass
    db.execute("DELETE FROM applications WHERE id=?", (aid,))  # history and steps are deleted by CASCADE


def purge_user_work(db, uid):
    """Erase one user's work: his records (with attachment files), his Department
    Database rows (with attachment files), his invoices and his public QR links.
    Used when a deleted user is erased for good and the admin chose 'yes, delete
    his work too', and when a deleted user reaches the end of his 30 days."""
    for rid in [r[0] for r in db.execute("SELECT id FROM records WHERE owner_id=?", (uid,))]:
        purge_record(db, rid)
    for _rid in [r[0] for r in db.execute("SELECT id FROM ddb_rows WHERE owner_id=?", (uid,))]:
        purge_ddb_row(db, _rid)
    for _aid in [r[0] for r in db.execute("SELECT id FROM applications WHERE owner_id=?", (uid,))]:
        purge_application(db, _aid)
    db.execute("DELETE FROM invoices WHERE owner_id=?", (uid,))
    db.execute("DELETE FROM public_links WHERE owner_id=?", (uid,))


def purge_user_account(db, uid, delete_work):
    """Erase a deleted user account for good.
    delete_work=True: his work goes at once, then the account row is removed
    (references that would block the delete are cleared first).
    delete_work=False: the account only leaves the Recycle Bin list; the account
    row and his work stay until the 30 days end, when purge_expired removes both."""
    if not delete_work:
        db.execute("UPDATE users SET bin_purged=1 WHERE id=?", (uid,))
        return
    purge_user_work(db, uid)
    db.execute("UPDATE records SET deleted_by=NULL WHERE deleted_by=?", (uid,))
    db.execute("UPDATE ddb_rows SET deleted_by=NULL WHERE deleted_by=?", (uid,))
    db.execute("UPDATE applications SET deleted_by=NULL WHERE deleted_by=?", (uid,))
    db.execute("UPDATE applications SET recipient_id=NULL WHERE recipient_id=?", (uid,))
    db.execute("UPDATE applications SET checker_id=NULL WHERE checker_id=?", (uid,))
    db.execute("UPDATE applications SET approver_id=NULL WHERE approver_id=?", (uid,))
    db.execute("UPDATE application_steps SET user_id=NULL WHERE user_id=?", (uid,))
    db.execute("UPDATE invoice_steps SET user_id=NULL WHERE user_id=?", (uid,))
    db.execute("UPDATE item_request_steps SET user_id=NULL WHERE user_id=?", (uid,))
    db.execute("UPDATE item_requests SET recipient_id=NULL WHERE recipient_id=?", (uid,))
    db.execute("UPDATE applications SET signature_by=NULL WHERE signature_by=?", (uid,))
    db.execute("UPDATE application_history SET user_id=NULL WHERE user_id=?", (uid,))
    db.execute("UPDATE record_shares SET shared_by=NULL WHERE shared_by=?", (uid,))
    db.execute("UPDATE record_user_shares SET shared_by=NULL WHERE shared_by=?", (uid,))
    db.execute("UPDATE repairs SET created_by=NULL WHERE created_by=?", (uid,))
    db.execute("UPDATE attachments SET uploaded_by=NULL WHERE uploaded_by=?", (uid,))
    db.execute("UPDATE record_history SET user_id=NULL WHERE user_id=?", (uid,))
    db.execute("UPDATE ddb_history SET user_id=NULL WHERE user_id=?", (uid,))
    db.execute("UPDATE invoice_template_shares SET shared_by=NULL WHERE shared_by=?", (uid,))
    db.execute("UPDATE invoice_dept_shares SET shared_by=NULL WHERE shared_by=?", (uid,))
    db.execute("UPDATE ddb_row_shares SET created_by=NULL WHERE created_by=?", (uid,))
    db.execute("UPDATE invoice_templates SET created_by=NULL WHERE created_by=?", (uid,))
    db.execute("UPDATE ddb_tabs SET created_by=NULL WHERE created_by=?", (uid,))
    db.execute("UPDATE ddb_delegates SET granted_by=NULL WHERE granted_by=?", (uid,))
    db.execute("UPDATE users SET deleted_by=NULL WHERE deleted_by=?", (uid,))
    db.execute("DELETE FROM transfers WHERE from_user=? OR to_user=?", (uid, uid))
    db.execute("DELETE FROM requests WHERE requester_id=?", (uid,))
    db.execute("UPDATE requests SET decided_by=NULL WHERE decided_by=?", (uid,))
    db.execute("DELETE FROM comments WHERE user_id=?", (uid,))
    # The user's own signature (My settings) goes with the account.
    _sig = db.execute("SELECT signature_path FROM users WHERE id=?", (uid,)).fetchone()
    if _sig and _sig["signature_path"]:
        try:
            os.remove(os.path.join(config.UPLOAD_DIR, "user_signatures", os.path.basename(_sig["signature_path"])))
        except Exception:
            pass
    db.execute("DELETE FROM users WHERE id=?", (uid,))


def purge_expired(db):
    """Erase records that stayed in the bin too long and trim the old activity log."""
    ids = [r[0] for r in db.execute(
        "SELECT id FROM records WHERE deleted_at IS NOT NULL "
        "AND deleted_at < datetime('now','localtime',?)", (f"-{config.BIN_DAYS} days",))]
    for rid in ids:
        purge_record(db, rid)
    db.execute("DELETE FROM activity_log WHERE created_at < datetime('now','localtime',?)",
               (f"-{config.ACTIVITY_KEEP_DAYS} days",))
    db.execute("DELETE FROM reminder_sent WHERE sent_on < date('now','localtime','-90 days')")
    db.execute("DELETE FROM signature_reminder_sent WHERE sent_on < date('now','localtime','-90 days')")
    for _rid in [r[0] for r in db.execute(
            "SELECT id FROM ddb_rows WHERE deleted_at IS NOT NULL AND deleted_at < datetime('now','localtime',?)",
            (f"-{config.BIN_DAYS} days",))]:
        purge_ddb_row(db, _rid)
    # Deleted application letters: after 30 days the letter and its uploaded
    # signature are erased for good, the same as a deleted record or row.
    for _aid in [r[0] for r in db.execute(
            "SELECT id FROM applications WHERE deleted_at IS NOT NULL AND deleted_at < datetime('now','localtime',?)",
            (f"-{config.BIN_DAYS} days",))]:
        purge_application(db, _aid)
    # Deleted users: after 30 days the account AND all his work go, together.
    for _uid in [r[0] for r in db.execute(
            "SELECT id FROM users WHERE is_deleted=1 AND deleted_at IS NOT NULL "
            "AND deleted_at < datetime('now','localtime',?)", (f"-{config.BIN_DAYS} days",))]:
        purge_user_account(db, _uid, delete_work=True)
    db.commit()
    return len(ids)


# ---------------------------------------------------------------- reminders and CSV
def reminder_rows(db, user, start, end, newest_first=False, limit=500):
    """Records whose reminder date (for example warranty end) is between start and end."""
    vis, params = visible_clause(db, user)
    sql = (rec_select(", v.value AS reminder_date, c.name AS reminder_name") +
           " JOIN record_values v ON v.record_id=r.id "
           "JOIN columns c ON c.id=v.column_id AND c.is_reminder=1 AND c.removed_at IS NULL "
           "WHERE r.deleted_at IS NULL AND " + vis + " AND substr(v.value,1,10) BETWEEN ? AND ? "
           "ORDER BY v.value " + ("DESC" if newest_first else "ASC") + " LIMIT ?")
    return db.execute(sql, params + [start, end, limit]).fetchall()


def build_csv(db, rows, with_owner):
    """Header and rows for a CSV download."""
    header, out, _kinds = build_table(db, rows, with_owner)
    return header, out


def build_table(db, rows, with_owner):
    """(header, rows, kinds) for CSV, Excel and PDF. Columns with the same name share one
    output column. kinds tells which output columns hold numbers."""
    vals = values_for(db, [r["id"] for r in rows])
    dept_cols, names, seen, numeric = {}, [], set(), {}
    for r in rows:
        d = r["department_id"]
        if d not in dept_cols:
            dept_cols[d] = get_columns(db, d)
            for c in dept_cols[d]:
                key = c["name"].lower()
                if key not in seen:
                    seen.add(key)
                    names.append(c["name"])
                numeric[key] = numeric.get(key, True) and c["col_type"] == "number"
    with_dept = with_owner or len(dept_cols) > 1
    header = (["Department"] if with_dept else []) + (["Owner", "Username"] if with_owner else []) \
        + names + ["Last updated"]
    out = []
    for r in rows:
        by_name = {c["name"].lower(): vals[r["id"]].get(c["id"]) for c in dept_cols[r["department_id"]]}
        line = ([r["department_name"]] if with_dept else []) \
            + ([r["owner_name"], r["owner_username"]] if with_owner else []) \
            + [by_name.get(n.lower()) for n in names] + [r["updated_at"]]
        out.append(line)
    fixed = (1 if with_dept else 0) + (2 if with_owner else 0)
    kinds = ["text"] * fixed + ["number" if numeric.get(n.lower()) else "text" for n in names] + ["text"]
    return header, out, kinds


def summaries_for(db, rows):
    """{record_id: short title} for a list of records (used by bin, reminders, lists)."""
    vals = values_for(db, [r["id"] for r in rows])
    cols, out = {}, {}
    for r in rows:
        d = r["department_id"]
        if d not in cols:
            cols[d] = get_columns(db, d)
        out[r["id"]] = summary_of(cols[d], vals[r["id"]])
    return out


# ---------------------------------------------------------------- date + time values
def split_when(value):
    """'2026-11-04 15:30' -> (date, 'HH:MM' or ''). A date-only value gives an empty time."""
    value = (value or "").strip()
    return value[:10], (value[11:16] if len(value) >= 16 else "")


def clock_text(hhmm):
    """'15:30' -> '3:30 PM' (empty text stays empty)."""
    if not hhmm:
        return ""
    try:
        return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return hhmm


def show_when(value):
    """How a date (and time) is shown: '2026-11-04' or '2026-11-04 3:30 PM'."""
    day, clock = split_when(value)
    return f"{day} {clock_text(clock)}".strip() if clock else day


def parse_when(value):
    """(date, time or None) from a stored value, or None when it is not a valid date."""
    day, clock = split_when(value)
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        return None
    t = None
    if clock:
        try:
            t = datetime.strptime(clock, "%H:%M").time()
        except ValueError:
            t = None
    return d, t


# ---------------------------------------------------------------- reminder notifications
def record_title(columns, vals, skip_ids=()):
    """Short name of a record for a notification: its first two filled text/dropdown/number values."""
    parts = [vals.get(c["id"]) for c in columns
             if c["col_type"] in ("text", "dropdown", "number") and c["id"] not in skip_ids
             and vals.get(c["id"])]
    return (" · ".join(parts[:2]) or "(record)")[:80]


def _when_words(days_left):
    return "today" if days_left == 0 else "tomorrow" if days_left == 1 else f"in {days_left} days"


def send_reminder_notifications(db, now=None):
    """Put one bell message per record and reminder column in the OWNER's bell:
    1 day before, on the day itself, and at the number of days the owner chose (1, 3 or 7).
    Nothing is sent before config.REMINDER_HOUR (the morning). Safe to call again and again:
    the reminder_sent table makes sure every message is sent only once. Returns how many were sent."""
    now = now or datetime.now()
    if now.hour < config.REMINDER_HOUR:
        return 0
    today = now.date()
    rows = db.execute(
        "SELECT r.id AS rid, r.owner_id, r.department_id, v.column_id, v.value, c.name AS cname, "
        "u.warn_days FROM record_values v "
        "JOIN columns c ON c.id=v.column_id AND c.is_reminder=1 AND c.removed_at IS NULL "
        "JOIN records r ON r.id=v.record_id AND r.deleted_at IS NULL "
        "JOIN users u ON u.id=r.owner_id AND u.is_active=1 "
        "WHERE substr(v.value,1,10) BETWEEN ? AND ?",
        (today.isoformat(), (today + timedelta(days=max(config.WARN_DAY_CHOICES))).isoformat())).fetchall()
    sent, cache = 0, {}
    for r in rows:
        when = parse_when(r["value"])
        if when is None:
            continue
        day, clock = when
        left = (day - today).days
        if left not in {0, 1, r["warn_days"] if r["warn_days"] in config.WARN_DAY_CHOICES else 3}:
            continue
        if left == 0 and clock is not None and clock < now.time():
            continue                                    # today's meeting time has already passed
        if db.execute("INSERT OR IGNORE INTO reminder_sent(record_id,column_id,value,offset_days) "
                      "VALUES (?,?,?,?)", (r["rid"], r["column_id"], r["value"], left)).rowcount == 0:
            continue                                    # this one was sent before
        if r["rid"] not in cache:
            cols = get_columns(db, r["department_id"])
            reminder_ids = {c["id"] for c in cols if c["is_reminder"]}
            cache[r["rid"]] = record_title(cols, values_for(db, [r["rid"]])[r["rid"]], reminder_ids)
        at = f" at {clock_text(clock.strftime('%H:%M'))}" if clock is not None else ""
        notify(db, [r["owner_id"]], f"{r['cname']}: {cache[r['rid']]} is {_when_words(left)}{at}",
               f"/records/{r['rid']}")
        sent += 1
    return sent


def send_ddb_meeting_notifications(db, now=None):
    """Department Database meeting notifications: a row in a meeting-notify tab with a
    date column that also keeps a time (has_time) is a meeting schedule. The row
    owner and every dept admin of that department get a bell message 7, 3 and 1 days
    before the meeting and again on the morning of the meeting (after
    config.REMINDER_HOUR, like record reminders). Dept admin text
    is exactly: "<USER> has a meeting at <date time>". Owner text: "You have a meeting
    at <date time>". Each (row, column, value, day-offset, person) is sent only once,
    so changing the date/time sends a new set for the new time. Returns how many were sent."""
    now = now or datetime.now()
    if now.hour < config.REMINDER_HOUR:
        return 0
    today = now.date()
    rows = db.execute(
        "SELECT r.id AS rid, r.owner_id, r.department_id, v.column_id, v.value, c.name AS cname, "
        "u.full_name AS owner_name FROM ddb_values v "
        "JOIN ddb_columns c ON c.id=v.column_id AND c.col_type='date' AND c.has_time=1 AND c.removed_at IS NULL "
        "JOIN ddb_tabs tb ON tb.id=c.tab_id AND tb.meeting_notify=1 AND tb.removed_at IS NULL "
        "JOIN ddb_rows r ON r.id=v.row_id AND r.deleted_at IS NULL "
        "JOIN users u ON u.id=r.owner_id AND u.is_active=1 "
        "WHERE substr(v.value,1,10) BETWEEN ? AND ?",
        (today.isoformat(), (today + timedelta(days=7)).isoformat())).fetchall()
    sent = 0
    for r in rows:
        when = parse_when(r["value"])
        if when is None:
            continue
        day, clock = when
        left = (day - today).days
        if left not in (0, 1, 3, 7):
            continue
        if left == 0 and clock is not None and clock < now.time():
            continue
        admins = [x[0] for x in db.execute(
            "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1 "
            "UNION SELECT user_id FROM ddb_delegates WHERE department_id=?",
            (r["department_id"], r["department_id"])).fetchall()]
        recipients = []
        if r["owner_id"] not in recipients:
            recipients.append(r["owner_id"])
        for a in admins:
            if a not in recipients:
                recipients.append(a)
        when_text = show_when(r["value"])
        for uid in recipients:
            if db.execute("INSERT OR IGNORE INTO ddb_meeting_sent(row_id,column_id,value,offset_days,user_id) "
                          "VALUES (?,?,?,?,?)", (r["rid"], r["column_id"], r["value"], left, uid)).rowcount == 0:
                continue
            text = (f"You have a meeting at {when_text}" if uid == r["owner_id"]
                    else f"{r['owner_name']} has a meeting at {when_text}")
            notify(db, [uid], text, ddb_row_link(db, r["rid"]))
            sent += 1
    return sent


def send_signature_reminder_notifications(db, now=None):
    """Daily morning reminder to upload a signature (2026-11-14): every
    morning, from config.REMINDER_HOUR like the other morning reminders,
    every active, approved user who has NOT uploaded a signature in My
    settings gets one bell message: "Please upload your signature from
    my settings", linked to /my-settings. The true portal admin
    (role 'admin') and the administrative permission users
    (can_portal_admin=1) never get it. Safe to call again and again: the
    signature_reminder_sent table makes sure each user gets it only once
    a day, so it comes again the next morning until they upload one —
    and stops the morning after they do (or starts again if they remove
    their signature). Returns how many were sent."""
    now = now or datetime.now()
    if now.hour < config.REMINDER_HOUR:
        return 0
    today = now.date().isoformat()
    rows = db.execute(
        "SELECT id FROM users WHERE is_active=1 AND is_deleted=0 AND approval_status='approved' "
        "AND role != 'admin' AND can_portal_admin=0 "
        "AND (signature_path IS NULL OR signature_path='')").fetchall()
    sent = 0
    for r in rows:
        if db.execute("INSERT OR IGNORE INTO signature_reminder_sent(user_id, sent_on) "
                      "VALUES (?,?)", (r["id"], today)).rowcount == 0:
            continue                                    # this user was already told today
        notify(db, [r["id"]], "Please upload your signature from my settings", "/my-settings")
        sent += 1
    return sent


def ddb_attachment_info(value):
    """ddb_values text for an attachment column -> {'stored','original'} or None."""
    if not value:
        return None
    try:
        import json as _json
        info = _json.loads(value)
        if isinstance(info, dict) and info.get("stored") and info.get("original"):
            return info
    except Exception:
        return None
    return None


def ddb_display_value(col, value):
    """What to show for a deptdb value: attachment columns show the original file name, not the JSON."""
    if col["col_type"] == "attachment":
        info = ddb_attachment_info(value)
        return info["original"] if info else ""
    return value


# ---------------------------------------------------------------- notifications
def notify(db, user_ids, text, link=None, skip=None):
    """Put a message in the bell of each user (never for 'skip', the person who acted).
    'skip' is one user id, or a list of them (2026-11-14: the application
    send tells the checker directly, so the watcher notification skips the
    checker too — otherwise a checker who is also a department admin gets
    the same news twice)."""
    if isinstance(skip, (list, tuple, set)):
        skips = set(skip)
    elif skip is not None:
        skips = {skip}
    else:
        skips = set()
    for uid in set(user_ids or []):
        if uid and uid not in skips:
            db.execute("INSERT INTO notifications(user_id,text,link) VALUES (?,?,?)", (uid, text[:300], link))


def dept_member_ids(db, dept_id):
    return [r[0] for r in db.execute("SELECT id FROM users WHERE department_id=? AND is_active=1", (dept_id,))]


def admin_ids(db):
    return [r[0] for r in db.execute("SELECT id FROM users WHERE (role='admin' OR can_portal_admin=1) AND is_active=1")]


def true_admin_ids(db):
    """The original portal admin accounts (role 'admin'), active."""
    return [r[0] for r in db.execute("SELECT id FROM users WHERE role='admin' AND is_active=1")]


def permission_user_ids(db):
    """Users given portal administrative permission (not true admins), active."""
    return [r[0] for r in db.execute("SELECT id FROM users WHERE role != 'admin' AND can_portal_admin=1 AND is_active=1")]


def notify_admin_task(db, actor, text, link=None, skip=None):
    """A permission user did an admin task: tell the true portal admins.
    Nothing is ever sent about a true portal admin's own task, and the
    actor is never told about his own task."""
    if is_true_admin(actor):
        return
    notify(db, true_admin_ids(db), text, link, skip=[actor["id"], skip])


def notify_dept_task(db, actor, text, link=None, skip=None):
    """A dept admin did a dept task: tell the true portal admins and the
    permission users. Nothing is sent about a true portal admin's task,
    and the actor is never told about his own task."""
    if is_true_admin(actor):
        return
    notify(db, true_admin_ids(db) + permission_user_ids(db), text, link, skip=[actor["id"], skip])


def notify_ddb_row_task(db, actor, dept_id, text, link=None, skip=None):
    """A user did something to a Department Database row: tell that
    department's dept admins. A dept admin (or delegate) acting on a row
    is a dept task, not a user task, so the caller routes those through
    notify_dept_task instead; a portal admin or permission user acting
    on a row goes through notify_admin_task."""
    if is_true_admin(actor):
        return
    targets = [r[0] for r in db.execute(
        "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1", (dept_id,))]
    notify(db, targets, text, link, skip=[actor["id"], skip])


def notify_ddb_task(db, actor, dept, text, link=None, skip=None):
    """Route a Department Database action to its watchers (2026-11-05):
    a true portal admin's action tells nobody; a permission user's action
    tells the true portal admins; a dept admin's or delegate's action
    tells the true portal admins and the permission users; a regular
    user's action tells that department's dept admins. 'skip' is one more
    user who must not be told (2026-11-14: the checker, who is already
    told directly when an application is sent to them)."""
    if is_true_admin(actor):
        return
    if is_portal_admin(actor):
        notify_admin_task(db, actor, text, link, skip=skip)
    elif ddb_is_tab_admin(db, actor, dept["id"]):
        notify_dept_task(db, actor, text, link, skip=skip)
    else:
        notify_ddb_row_task(db, actor, dept["id"], text, link, skip=skip)


# ---------------------------------------------------------------- sharing
def share_with_department(db, user, rec, dept_id, dept_name, permission, quiet=False):
    """Share a record with a whole department, or change the permission. Returns 'new', 'changed' or None."""
    permission = clean_permission(permission)
    row = db.execute("SELECT permission FROM record_shares WHERE record_id=? AND department_id=?",
                     (rec["id"], dept_id)).fetchone()
    if row is None:
        db.execute("INSERT INTO record_shares(record_id,department_id,shared_by,permission) VALUES (?,?,?,?)",
                   (rec["id"], dept_id, user["id"], permission))
        add_history(db, rec["id"], user, "shared", new=f"{dept_name} (whole department, {PERM_WORDS[permission]})")
        if not quiet:
            notify(db, dept_member_ids(db, dept_id),
                   f"{user['full_name']} shared a record with your department ({PERM_WORDS[permission]}).",
                   f"/records/{rec['id']}", skip=user["id"])
        return "new"
    if row["permission"] != permission:
        db.execute("UPDATE record_shares SET permission=? WHERE record_id=? AND department_id=?",
                   (permission, rec["id"], dept_id))
        add_history(db, rec["id"], user, "share_changed", dept_name,
                    PERM_WORDS[row["permission"]], PERM_WORDS[permission])
        if not quiet:
            notify(db, dept_member_ids(db, dept_id),
                   f"A record shared with your department is now: {PERM_WORDS[permission]}.",
                   f"/records/{rec['id']}", skip=user["id"])
        return "changed"
    return None


def share_with_user(db, user, rec, target, permission, quiet=False):
    """Share a record with one chosen person, or change the permission. Returns 'new', 'changed' or None."""
    permission = clean_permission(permission)
    row = db.execute("SELECT permission FROM record_user_shares WHERE record_id=? AND user_id=?",
                     (rec["id"], target["id"])).fetchone()
    if row is None:
        db.execute("INSERT INTO record_user_shares(record_id,user_id,permission,shared_by) VALUES (?,?,?,?)",
                   (rec["id"], target["id"], permission, user["id"]))
        add_history(db, rec["id"], user, "shared_user", new=f"{target['full_name']} ({PERM_WORDS[permission]})")
        if not quiet:
            notify(db, [target["id"]], f"{user['full_name']} shared a record with you ({PERM_WORDS[permission]}).",
                   f"/records/{rec['id']}", skip=user["id"])
        return "new"
    if row["permission"] != permission:
        db.execute("UPDATE record_user_shares SET permission=? WHERE record_id=? AND user_id=?",
                   (permission, rec["id"], target["id"]))
        add_history(db, rec["id"], user, "share_changed", target["full_name"],
                    PERM_WORDS[row["permission"]], PERM_WORDS[permission])
        if not quiet:
            notify(db, [target["id"]], f"A record shared with you is now: {PERM_WORDS[permission]}.",
                   f"/records/{rec['id']}", skip=user["id"])
        return "changed"
    return None


# ---------------------------------------------------------------- sorting and filtering lists
def sort_clause(db, sort, direction):
    """(ORDER BY text, params). sort = updated | created | col:<column name>."""
    d = "ASC" if direction == "asc" else "DESC"
    if sort == "created":
        return f"r.created_at {d}, r.id {d}", []
    if (sort or "").startswith("col:"):
        name = sort[4:]
        # Per-record department, not global: a column named e.g. "Amount"
        # may be a number column in one department and a text column in
        # another. The value lookup and the number check both use the
        # record's own department (r.department_id), so sorting a list
        # that spans departments no longer casts text values as numbers
        # just because some other department has a number column of the
        # same name. Params, in order: sub in IS NULL, number check,
        # sub in CAST, sub in ELSE.
        sub = ("(SELECT v.value FROM record_values v JOIN columns c ON c.id=v.column_id "
               "AND c.removed_at IS NULL AND c.department_id=r.department_id "
               "WHERE v.record_id=r.id AND lower(c.name)=lower(?) LIMIT 1)")
        is_number = ("(SELECT 1 FROM columns WHERE department_id=r.department_id "
                     "AND lower(name)=lower(?) AND col_type='number' AND removed_at IS NULL LIMIT 1)")
        expr = f"CASE WHEN {is_number} IS NOT NULL THEN CAST({sub} AS REAL) ELSE {sub} COLLATE NOCASE END"
        return f"({sub} IS NULL), {expr} {d}, r.id DESC", [name, name, name, name]
    return f"r.updated_at {d}, r.id {d}", []


def filter_clause(name, value):
    """SQL for 'column NAME contains VALUE'."""
    if not (name and value):
        return "", []
    return (" AND EXISTS (SELECT 1 FROM record_values v JOIN columns c ON c.id=v.column_id "
            "AND c.removed_at IS NULL WHERE v.record_id=r.id AND lower(c.name)=lower(?) "
            "AND v.value LIKE ? ESCAPE '\\')", [name, like_pattern(value)])


def column_names(db, user):
    """Column names the user can sort/filter by (from the departments they can see)."""
    if is_portal_admin(user):
        rows = db.execute("SELECT DISTINCT name FROM columns WHERE removed_at IS NULL AND shown=1 "
                          "ORDER BY name COLLATE NOCASE").fetchall()
    else:
        depts = [user["department_id"]] + viewable_departments(db, user)
        rows = db.execute("SELECT DISTINCT name FROM columns WHERE removed_at IS NULL AND shown=1 "
                          "AND department_id IN (%s) ORDER BY name COLLATE NOCASE" % ",".join("?" * len(depts)),
                          depts).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["name"].lower() not in seen:
            seen.add(r["name"].lower())
            out.append(r["name"])
    return out


# ---------------------------------------------------------------- public QR links
def new_token():
    """Long random code for a public link (about 128 bits: cannot be guessed)."""
    return secrets.token_urlsafe(16)


def names_for_records(db, record_ids):
    """Distinct (lower-case key, display name) of the columns of the given records' departments."""
    if not record_ids:
        return []
    q = ",".join("?" * len(record_ids))
    rows = db.execute(f"SELECT DISTINCT c.name FROM columns c JOIN records r ON r.department_id=c.department_id "
                      f"WHERE r.id IN ({q}) AND c.removed_at IS NULL AND c.shown=1 "
                      f"ORDER BY c.position, c.id", list(record_ids)).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["name"].lower() not in seen:
            seen.add(r["name"].lower())
            out.append(r["name"])
    return out


def public_fields_of(link):
    return [f for f in (link["fields"] or "").split("\n") if f]


def public_view(db, rec, fields, full=False):
    """[(label, value)] of one record: the chosen fields (or EVERY column when full=True),
    only the filled ones. Dates show their time as '2026-11-04 3:30 PM'."""
    vals = values_for(db, [rec["id"]])[rec["id"]]
    out = []
    for c in get_columns(db, rec["department_id"]):
        if (full or c["name"].lower() in fields) and vals.get(c["id"]):
            out.append((c["name"], show_when(vals[c["id"]]) if c["col_type"] == "date" else vals[c["id"]]))
    return out


# ---------------------------------------------------------------- the unique QR code HRC-<number>
CODE_PREFIX = "HRC-"


def format_code(n):
    """Number -> 'HRC-12' (kept for old sequential codes)."""
    return f"{CODE_PREFIX}{int(n)}"


def display_code(link):
    """The code shown under a public QR: only the random HRC-##### code_text.

    The old sequential code_no is never shown any more, because showing it
    would make it searchable again. A link missing code_text (it should not
    happen: the upgrade backfills one) shows no code, not a sequential one."""
    if link is None:
        return ""
    try:
        return link["code_text"] or ""
    except Exception:
        return ""


def parse_code_text(text):
    """'HRC-48392' / 'hrc 48392' -> 'HRC-48392'. Anything else -> None."""
    m = re.fullmatch(r"\s*HRC[-\s]?(\d{5})\s*", text or "", re.IGNORECASE)
    return f"HRC-{m.group(1)}" if m else None


def new_random_code_text(db):
    """A random HRC-##### code not used by any public link, invoice,
    item request, application letter or Department Database row (the Search
    QR page looks all over for a code, so every code must be unique everywhere)."""
    import secrets as _secrets
    for _ in range(200):
        cand = f"HRC-{_secrets.randbelow(90000) + 10000}"
        if db.execute("SELECT 1 FROM public_links WHERE code_text=?", (cand,)).fetchone() is None:
            try:
                if db.execute("SELECT 1 FROM invoices WHERE public_code=?", (cand,)).fetchone() is None:
                    if db.execute("SELECT 1 FROM item_requests WHERE public_code=?", (cand,)).fetchone() is None:
                        if db.execute("SELECT 1 FROM applications WHERE public_code=?", (cand,)).fetchone() is None:
                            if db.execute("SELECT 1 FROM ddb_rows WHERE public_code=?", (cand,)).fetchone() is None:
                                return cand
            except Exception:
                return cand
    return None


def public_base_url(db):
    """Base address printed on public QR codes (invoice, request, record,
    Department Database row). The portal admin sets it once in Portal
    settings (for example http://192.168.1.116:8100, the address the
    office opens in a browser). When it is not set, the address the
    portal is being opened from right now is used, so a QR made while
    browsing the portal still opens. The old hard-coded https://portal
    host is never used: a phone cannot open it."""
    from models import setting_get
    base = (setting_get(db, "public_base_url", "") or "").strip().rstrip("/")
    if base:
        return base
    try:
        from flask import request
        return (request.host_url or "").rstrip("/")
    except Exception:
        return ""


def external_url(db, endpoint, **values):
    """Full external URL for a public QR code. Uses the public base
    address when the admin set one, otherwise the current request host."""
    from flask import url_for
    base = public_base_url(db)
    path = url_for(endpoint, **values)
    if base:
        return base + path
    return url_for(endpoint, _external=True, **values)


def parse_code(text):
    """'hrc-12', 'HRC 12' or 'HRC12' -> 12. Anything else -> None."""
    m = re.fullmatch(r"\s*HRC[-\s]?(\d{1,12})\s*", text or "", re.IGNORECASE)
    return int(m.group(1)) if m else None


def next_code_no(db):
    """The next free number, starting at 0. A number is never given twice, even when a QR
    is turned off or deleted (the counter only goes up)."""
    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('hrc_next','0')")
    db.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='hrc_next'")   # takes the write lock
    return int(db.execute("SELECT value FROM settings WHERE key='hrc_next'").fetchone()[0]) - 1


def create_public_link(db, owner_id, kind, fields, full_record=False, title=None):
    """Create a public QR link with its unique code. Returns the new link id."""
    return db.execute(
        "INSERT INTO public_links(token,owner_id,title,kind,fields,full_record,code_no,code_text) VALUES (?,?,?,?,?,?,?,?)",
        (new_token(), owner_id, title, kind, "\n".join(fields), 1 if full_record else 0, next_code_no(db),
         new_random_code_text(db))).lastrowid


# ---------------------------------------------------------------- change of owner
def may_change_owner(user, rec):
    """The portal admin, and the department admin of the record's department."""
    return is_portal_admin(user) or bool(user["is_dept_admin"] and user["department_id"] == rec["department_id"])


def owner_candidates(db, user, rec):
    """Who the record may be given to: an admin may choose anybody, a department admin
    the members of the record's department."""
    sql = "SELECT id, full_name, username FROM users WHERE is_active=1 AND id != ?"
    params = [rec["owner_id"]]
    if not is_portal_admin(user):
        sql += " AND department_id=?"
        params.append(rec["department_id"])
    return db.execute(sql + " ORDER BY full_name", params).fetchall()


def change_owner(db, user, rec, new_owner_id):
    """Give a record to another person. Returns an error text or None."""
    if not may_change_owner(user, rec):
        return "You are not allowed to change the owner."
    target = db.execute("SELECT * FROM users WHERE id=? AND is_active=1", (new_owner_id,)).fetchone()
    if target is None:
        return "Choose a person."
    if target["id"] == rec["owner_id"]:
        return "That person already owns this record."
    if not is_portal_admin(user) and target["department_id"] != rec["department_id"]:
        return "A department admin can only give a record to a member of the same department."
    old = db.execute("SELECT full_name FROM users WHERE id=?", (rec["owner_id"],)).fetchone()
    db.execute("UPDATE records SET owner_id=?, version=version+1, updated_at=datetime('now','localtime') WHERE id=?",
               (target["id"], rec["id"]))
    db.execute("DELETE FROM record_user_shares WHERE record_id=? AND user_id=?",
               (rec["id"], target["id"]))                        # an owner needs no personal share
    add_history(db, rec["id"], user, "owner_changed", old=old["full_name"] if old else "", new=target["full_name"])
    notify(db, [target["id"]], f"{user['full_name']} made you the owner of a record.",
           f"/records/{rec['id']}", skip=user["id"])
    notify(db, [rec["owner_id"]], f"{user['full_name']} gave your record to {target['full_name']}.",
           f"/records/{rec['id']}", skip=user["id"])
    return None


# ================================================================ department database
# One shared table per department. The department admin (or a "manager") decides the columns
# and who may do what; normal users add and maintain their own rows.
DDB_LEVELS = (("view", "View only"),
              ("own", "Add and manage own rows"),
              ("edit", "Edit every row"),
              ("manager", "Manager (works as the department admin)"))
DDB_LEVEL_WORDS = dict(DDB_LEVELS)


def ddb_level(db, user, dept_id):
    """This user's level in the department database of dept_id: manager / edit / own / view / None.
    The portal admin and the department admin are always managers. Everybody else in the
    department is 'own' (add and manage own rows) unless a manager chose another level."""
    if is_portal_admin(user):
        return "manager"
    if user["department_id"] != dept_id:
        return None
    if user["is_dept_admin"]:
        return "manager"
    row = db.execute("SELECT level FROM ddb_perms WHERE department_id=? AND user_id=?",
                     (dept_id, user["id"])).fetchone()
    return row["level"] if row and row["level"] in DDB_LEVEL_WORDS else "own"


def ddb_columns(db, dept_id, only_shown=True, tab_id=None):
    sql = "SELECT * FROM ddb_columns WHERE department_id=? AND removed_at IS NULL"
    params = [dept_id]
    if tab_id is not None:
        sql += " AND tab_id=?"
        params.append(tab_id)
    if only_shown:
        sql += " AND shown=1"
    return db.execute(sql + " ORDER BY position, id", params).fetchall()


def ddb_tabs(db, dept_id):
    return db.execute("SELECT * FROM ddb_tabs WHERE department_id=? AND removed_at IS NULL ORDER BY position, id",
                      (dept_id,)).fetchall()


def first_text_value(db, row_id):
    """The value of a row's first text/longtext column (its display name)."""
    row = db.execute(
        "SELECT v.value FROM ddb_values v JOIN ddb_columns c ON c.id=v.column_id "
        "AND c.col_type IN ('text','longtext') AND c.removed_at IS NULL "
        "WHERE v.row_id=? ORDER BY c.position, c.id LIMIT 1", (row_id,)).fetchone()
    return row["value"] if row and row["value"] else None


def design_rail(db, user, dept_id=None, tab_id=None):
    """Data for the Design 6 right rail and the "rows added this week" chart.
    Everything returned is data this user is already allowed to see: meetings
    and recently changed rows in one department they can view, and row counts
    for the tab they are looking at. Returns {} with no user or no department.
    """
    if user is None:
        return {}
    dept = None
    if dept_id:
        row = db.execute("SELECT id FROM departments WHERE id=?", (dept_id,)).fetchone()
        if row and (is_portal_admin(user) or user["department_id"] == dept_id):
            dept = row["id"]
    if dept is None:
        dept = user["department_id"]
    if not dept:
        return {}
    today = date.today()
    end = today + timedelta(days=7)
    # Follow-ups: meetings (a date+time column in a meeting-notify tab) in the next 7 days.
    followups = []
    for m in db.execute(
            "SELECT r.id AS rid, v.value AS val, tb.name AS tab_name FROM ddb_values v "
            "JOIN ddb_columns c ON c.id=v.column_id AND c.col_type='date' AND c.has_time=1 AND c.removed_at IS NULL "
            "JOIN ddb_tabs tb ON tb.id=c.tab_id AND tb.meeting_notify=1 AND tb.removed_at IS NULL "
            "JOIN ddb_rows r ON r.id=v.row_id AND r.deleted_at IS NULL AND r.department_id=? "
            "WHERE substr(v.value,1,10) BETWEEN ? AND ? ORDER BY v.value LIMIT 3",
            (dept, today.isoformat(), end.isoformat())).fetchall():
        when = parse_when(m["val"])
        if when is None:
            continue
        day, clock = when
        followups.append({"day": "%02d" % day.day, "mon": day.strftime("%b").upper(),
                          "title": first_text_value(db, m["rid"]) or m["tab_name"],
                          "detail": show_when(m["val"]), "link": ddb_row_link(db, m["rid"])})
    # Recent activity: recently updated rows in this department.
    recent = []
    for r in db.execute(
            "SELECT r.id AS rid, r.updated_at, u.full_name AS owner_name, tb.name AS tab_name "
            "FROM ddb_rows r JOIN users u ON u.id=r.owner_id "
            "LEFT JOIN ddb_tabs tb ON tb.id=r.tab_id "
            "WHERE r.department_id=? AND r.deleted_at IS NULL "
            "ORDER BY r.updated_at DESC, r.id DESC LIMIT 3", (dept,)).fetchall():
        recent.append({"who": r["owner_name"],
                       "what": first_text_value(db, r["rid"]) or (r["tab_name"] or "row"),
                       "when": r["updated_at"][5:16], "link": ddb_row_link(db, r["rid"])})
    # Rows added this week (chart) for the tab being viewed.
    week = []
    if tab_id:
        days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        counts = {d: 0 for d in days}
        for row in db.execute(
                "SELECT date(created_at) AS d, COUNT(*) AS n FROM ddb_rows "
                "WHERE department_id=? AND tab_id=? AND deleted_at IS NULL "
                "AND date(created_at) BETWEEN ? AND ? GROUP BY date(created_at)",
                (dept, tab_id, days[0], days[-1])).fetchall():
            if row["d"] in counts:
                counts[row["d"]] = row["n"]
        top = max(counts.values()) or 1
        for d in days:
            dt = date.fromisoformat(d)
            week.append({"label": dt.strftime("%a")[:3], "n": counts[d],
                         "pct": round(100 * counts[d] / top, 1),
                         "hot": 1 if counts[d] == top and top > 0 else 0})
    return {"dept_id": dept, "followups": followups, "recent": recent, "week": week}


# ======================= Dashboard settings + department charts (2026-11-06) =======================
# One colour per department, from the portal's chart palette (teal first, the
# portal's main accent). Assigned by department id, so a department keeps its
# colour even when the counts change. The Records-by-status pie keeps the
# existing DONUT_COLORS order (green first) so its colours do not change.
DEPT_COLORS = ["#0b6e99", "#17a05d", "#e8a317", "#d9534f", "#7b61c4", "#9db3c1"]

DASHBOARD_SECTIONS = ["kpi", "records_by_dept", "ddb", "status",
                      "logged_in", "reminders", "quick"]
DASHBOARD_DEFAULTS = {"show": {s: True for s in DASHBOARD_SECTIONS},
                      "chart": {"records_by_dept": "bar", "ddb": "bar"}}


def dashboard_settings(db, user_id):
    """One admin's dashboard settings, merged over the defaults. Unknown keys
    and bad values are ignored, so a saved row never breaks the dashboard."""
    import json
    data = {}
    row = db.execute("SELECT settings_json FROM dashboard_settings WHERE user_id=?",
                     (user_id,)).fetchone()
    if row and row["settings_json"]:
        try:
            data = json.loads(row["settings_json"])
        except (ValueError, TypeError):
            data = {}
    out = {"show": dict(DASHBOARD_DEFAULTS["show"]),
           "chart": dict(DASHBOARD_DEFAULTS["chart"])}
    if isinstance(data.get("show"), dict):
        for k, v in data["show"].items():
            if k in out["show"]:
                out["show"][k] = bool(v)
    if isinstance(data.get("chart"), dict):
        for k, v in data["chart"].items():
            if k in out["chart"] and v in ("bar", "pie"):
                out["chart"][k] = v
    return out


def save_dashboard_settings(db, user_id, settings):
    """Store one admin's dashboard settings (one row per admin, upsert)."""
    import json
    db.execute(
        "INSERT INTO dashboard_settings (user_id, settings_json, updated_at) "
        "VALUES (?, ?, datetime('now','localtime')) "
        "ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json, "
        "updated_at=datetime('now','localtime')",
        (user_id, json.dumps(settings)))
    db.commit()


def dept_colours(db):
    """dept_id -> colour, stable by department id, cycling the palette."""
    rows = db.execute("SELECT id FROM departments ORDER BY id").fetchall()
    return {r["id"]: DEPT_COLORS[i % len(DEPT_COLORS)] for i, r in enumerate(rows)}


def ddb_dashboard_data(db):
    """Per-department Department Database totals + per-tab row counts, for the
    dashboard widget. Only active tabs with rows, plus the Invoices tab when
    the department has invoices. The total is the sum of the listed tabs, so
    the pie slices and the breakdown always agree."""
    tabs = db.execute(
        "SELECT t.department_id, t.name, COUNT(r.id) AS n FROM ddb_tabs t "
        "LEFT JOIN ddb_rows r ON r.tab_id=t.id AND r.deleted_at IS NULL "
        "WHERE t.removed_at IS NULL GROUP BY t.id "
        "ORDER BY t.department_id, t.position").fetchall()
    inv = {r["department_id"]: r["n"] for r in db.execute(
        "SELECT department_id, COUNT(*) AS n FROM invoices GROUP BY department_id").fetchall()}
    out = []
    for d in db.execute("SELECT id, name FROM departments ORDER BY name").fetchall():
        tab_list = [{"name": t["name"], "n": t["n"]}
                    for t in tabs if t["department_id"] == d["id"] and t["n"] > 0]
        inv_n = inv.get(d["id"], 0)
        if inv_n:
            tab_list.append({"name": "Invoices", "n": inv_n})
        out.append({"dept_id": d["id"], "name": d["name"],
                    "total": sum(t["n"] for t in tab_list), "tabs": tab_list})
    return out


def pie_svg(segments, size=360):
    """A filled pie chart as inline SVG (no hollow centre). segments is a list
    of (colour, count); the count is written on each slice in white bold text
    (white is the ink that reads on every slice colour — the same colour as
    its slice would disappear into it). A slice covering the whole pie is
    drawn as a full circle, because an arc from a point to itself draws
    nothing. Tiny slices (under 15 degrees) get no on-slice label, so labels
    never overlap. Returns "" when there is nothing to draw."""
    total = sum(c for _, c in segments)
    if total <= 0:
        return ""
    cx = cy = size // 2
    r = size // 2 - 15
    parts = [f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img">']
    start = 0.0
    for colour, count in segments:
        if count <= 0:
            continue
        sweep = 360.0 * count / total
        end = start + sweep
        if sweep >= 360.0:
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{colour}"/>')
            parts.append(
                f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" '
                f'font-size="26" font-weight="800" fill="#ffffff">{count}</text>')
            start = end
            continue
        s = math.radians(start)
        e = math.radians(end)
        x1 = cx + r * math.sin(s)
        y1 = cy - r * math.cos(s)
        x2 = cx + r * math.sin(e)
        y2 = cy - r * math.cos(e)
        large = 1 if sweep > 180 else 0
        parts.append(
            f'<path d="M {cx},{cy} L {x1:.1f},{y1:.1f} A {r},{r} 0 {large} 1 '
            f'{x2:.1f},{y2:.1f} Z" fill="{colour}"/>')
        if sweep >= 15:
            mid = math.radians(start + sweep / 2.0)
            lr = r * 0.62
            lx = cx + lr * math.sin(mid)
            ly = cy - lr * math.cos(mid)
            parts.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="26" font-weight="800" '
                f'fill="#ffffff">{count}</text>')
        start = end
    parts.append('</svg>')
    return ''.join(parts)


def ddb_is_tab_admin(db, user, dept_id):
    """Portal admin, dept admin, or a user the dept admin chose as a delegate
    for the Department Database — all may manage tabs, columns and any row."""
    if is_portal_admin(user):
        return True
    if user["department_id"] == dept_id and user["is_dept_admin"]:
        return True
    if user["department_id"] == dept_id:
        return db.execute("SELECT 1 FROM ddb_delegates WHERE department_id=? AND user_id=?",
                          (dept_id, user["id"])).fetchone() is not None
    return False


def ddb_can_view_row(db, user, row):
    """Every user in the same department can see every row in a tab. A row
    shared with another department or a specific user is also visible there."""
    if is_portal_admin(user):
        return True
    if user["department_id"] == row["department_id"]:
        return True
    if db.execute("SELECT 1 FROM ddb_row_shares WHERE row_id=? AND (user_id=? OR department_id=?)",
                  (row["id"], user["id"], user["department_id"])).fetchone():
        return True
    return False


def ddb_share_permission(db, user, row):
    """'edit' if this user (or his department) was shared the row with edit rights, else None."""
    r = db.execute("SELECT permission FROM ddb_row_shares WHERE row_id=? AND (user_id=? OR department_id=?) "
                   "ORDER BY CASE WHEN user_id IS NOT NULL THEN 0 ELSE 1 END LIMIT 1",
                   (row["id"], user["id"], user["department_id"])).fetchone()
    return r["permission"] if r else None


def ddb_can_add(db, user):
    """May this user add rows to the Department Database of his own department
    (and does it have a tab with columns)? Used for 'Copy to department database'."""
    if user["department_id"] is None:
        return False
    tabs = ddb_tabs(db, user["department_id"])
    return bool(tabs) and any(ddb_columns(db, user["department_id"], tab_id=tb["id"]) for tb in tabs)


def ddb_can_edit_row(db, user, row):
    """Only the owner may edit a row — unless a dept admin / delegate (who may
    edit every row in the department) or a share with edit permission says otherwise."""
    if ddb_is_tab_admin(db, user, row["department_id"]):
        return True
    if row["owner_id"] == user["id"]:
        return True
    return ddb_share_permission(db, user, row) == "edit"


def ddb_can_delete_row(db, user, row):
    return ddb_is_tab_admin(db, user, row["department_id"]) or row["owner_id"] == user["id"]


def ddb_values(db, row_ids):
    """{row_id: {column_id: value}} for many rows at once."""
    out = {rid: {} for rid in row_ids}
    ids = list(row_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in db.execute(f"SELECT row_id,column_id,value FROM ddb_values WHERE row_id IN ({q})", chunk):
            out[r["row_id"]][r["column_id"]] = r["value"]
    return out


def ddb_row_link(db, rid):
    """Link to a Department Database row in place: the list page on the row's
    own tab and page, with an anchor that highlights the row for a moment
    (2026-11-05). Used by notifications and by Locate so the row is found
    in context instead of opening the row detail page."""
    row = db.execute("SELECT department_id, tab_id, updated_at FROM ddb_rows WHERE id=?", (rid,)).fetchone()
    if row is None:
        return "/deptdb"
    before = db.execute(
        "SELECT COUNT(*) FROM ddb_rows WHERE tab_id=? AND deleted_at IS NULL "
        "AND (updated_at > ? OR (updated_at = ? AND id > ?))",
        (row["tab_id"], row["updated_at"], row["updated_at"], rid)).fetchone()[0]
    page = before // config.PER_PAGE + 1
    return f"/deptdb?dept={row['department_id']}&tab={row['tab_id']}&page={page}#row-{rid}"


def ddb_history(db, row_id, user, action, field=None, old=None, new=None):
    db.execute("INSERT INTO ddb_history(row_id,user_id,full_name,action,field,old_value,new_value) "
               "VALUES (?,?,?,?,?,?,?)",
               (row_id, user["id"] if user else None, user["full_name"] if user else None, action, field, old, new))


def ddb_create_row(db, user, dept_id, values, tab_id=None, source_record_id=None):
    rid = db.execute("INSERT INTO ddb_rows(department_id,tab_id,owner_id,source_record_id) VALUES (?,?,?,?)",
                     (dept_id, tab_id, user["id"], source_record_id)).lastrowid
    for cid, val in values.items():
        if val is not None:
            db.execute("INSERT INTO ddb_values(row_id,column_id,value) VALUES (?,?,?)", (rid, cid, val))
    ddb_history(db, rid, user, "created", new=f"copied from record #{source_record_id}" if source_record_id else None)
    return rid


def ddb_update_row(db, user, row, columns, new_values, version):
    """Save changes of a row. Returns 'ok', 'nochange' or 'conflict' (somebody saved first)."""
    old = ddb_values(db, [row["id"]])[row["id"]]
    changes = [(c, old.get(c["id"]), new_values[c["id"]]) for c in columns
               if (old.get(c["id"]) or None) != new_values[c["id"]]]
    if not changes:
        return "nochange"
    done = db.execute("UPDATE ddb_rows SET version=version+1, updated_at=datetime('now','localtime') "
                      "WHERE id=? AND version=? AND deleted_at IS NULL", (row["id"], version)).rowcount
    if done == 0:
        db.rollback()
        return "conflict"
    for col, before, after in changes:
        if after is None:
            db.execute("DELETE FROM ddb_values WHERE row_id=? AND column_id=?", (row["id"], col["id"]))
        else:
            db.execute("INSERT INTO ddb_values(row_id,column_id,value) VALUES (?,?,?) "
                       "ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value",
                       (row["id"], col["id"], after))
        if col["col_type"] == "attachment":
            before = ddb_display_value(col, before)
            after = ddb_display_value(col, after)
        ddb_history(db, row["id"], user, "edit", col["name"], before, after)
    return "ok"


def ddb_prefill_from_record(db, rec, dept_cols):
    """Values for a new department-database row, taken from a personal record: every
    department-database column whose NAME matches a column of the record gets its value."""
    by_name = {c["name"].lower(): c for c in get_columns(db, rec["department_id"], only_shown=False)}
    vals = values_for(db, [rec["id"]])[rec["id"]]
    out = {}
    for c in dept_cols:
        src = by_name.get(c["name"].lower())
        if src is not None and vals.get(src["id"]):
            value = vals[src["id"]]
            if c["col_type"] == "dropdown" and value not in options_of(c):
                continue                                   # not one of the allowed choices
            if c["col_type"] == "date":
                value = value[:16] if c["has_time"] else value[:10]
            out[c["id"]] = value
    return out
