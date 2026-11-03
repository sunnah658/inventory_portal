"""
core.py - the business logic of the portal (no web pages here).

Used by: routes_records.py, routes_admin.py, import_users.py, models.py
Uses:    config.py, models.py, templates_data.py, utils.py

What lives here: record columns, permission checks, reading/saving record values,
edit history, recycle bin, department creation and the CSV builder.
"""
import math
import os
import secrets
import shutil
from datetime import date, datetime, timedelta

import config
from models import log
from templates_data import TEMPLATES
from utils import like_pattern

COLUMN_TYPES = [("text", "Text"), ("longtext", "Long text"), ("number", "Number"),
                ("date", "Date"), ("dropdown", "Dropdown list"), ("yesno", "Yes / No")]
TYPE_LABEL = dict(COLUMN_TYPES)


# ---------------------------------------------------------------- columns
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
    dept_id = db.execute("INSERT INTO departments(name) VALUES (?)", (name,)).lastrowid
    create_department_columns(db, dept_id, template_key, selected)
    return dept_id


# ---------------------------------------------------------------- records: reading
def rec_select(extra=""):
    """Base SELECT for records with owner and department names."""
    return ("SELECT r.*, u.full_name AS owner_name, u.username AS owner_username, "
            "d.name AS department_name, d.attachments_enabled, d.attachment_max_mb" + extra +
            " FROM records r JOIN users u ON u.id=r.owner_id "
            "JOIN departments d ON d.id=r.department_id")


def get_record(db, rid):
    return db.execute(rec_select() + " WHERE r.id=?", (rid,)).fetchone()


def viewable_departments(db, user):
    """Departments this user may VIEW (not edit) besides their own."""
    return [r[0] for r in db.execute(
        "SELECT department_id FROM user_view_departments WHERE user_id=?", (user["id"],))]


def access_level(db, user, rec):
    """What this user is to this record:
    admin / owner / shared  - may edit
    supervisor              - department admin of the record's department: view and suggest only
    viewer                  - allowed to view that department: view and suggest only
    None                    - no access
    """
    if user["role"] == "admin":
        return "admin"
    if rec["owner_id"] == user["id"]:
        return "owner"
    if db.execute("SELECT 1 FROM record_shares WHERE record_id=? AND department_id=?",
                  (rec["id"], user["department_id"])).fetchone():
        return "shared"
    if user["is_dept_admin"] and rec["department_id"] == user["department_id"]:
        return "supervisor"
    if rec["department_id"] in viewable_departments(db, user):
        return "viewer"
    return None


EDIT_LEVELS = ("admin", "owner", "shared")
MANAGE_LEVELS = ("admin", "owner")


def visible_clause(db, user):
    """SQL (and params) for every record this user is allowed to see."""
    if user["role"] == "admin":
        return "1=1", []
    parts = ["r.owner_id=?",
             "EXISTS (SELECT 1 FROM record_shares s WHERE s.record_id=r.id AND s.department_id=?)"]
    params = [user["id"], user["department_id"]]
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
    """{record_id: [department names]} for many records at once."""
    out = {rid: [] for rid in record_ids}
    ids = list(record_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        for r in db.execute(f"SELECT s.record_id, d.name FROM record_shares s "
                            f"JOIN departments d ON d.id=s.department_id "
                            f"WHERE s.record_id IN ({q}) ORDER BY d.name", chunk):
            out[r["record_id"]].append(r["name"])
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
                           "columns": cols[d], "rows": []})
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


# ---------------------------------------------------------------- notifications
def notify(db, user_ids, text, link=None, skip=None):
    """Put a message in the bell of each user (never for 'skip', the person who acted)."""
    for uid in set(user_ids or []):
        if uid and uid != skip:
            db.execute("INSERT INTO notifications(user_id,text,link) VALUES (?,?,?)", (uid, text[:300], link))


def dept_member_ids(db, dept_id):
    return [r[0] for r in db.execute("SELECT id FROM users WHERE department_id=? AND is_active=1", (dept_id,))]


def admin_ids(db):
    return [r[0] for r in db.execute("SELECT id FROM users WHERE role='admin' AND is_active=1")]


def approver_ids(db, dept_id):
    """Who may decide requests of a department: all admins and the department's admins."""
    ids = admin_ids(db)
    ids += [r[0] for r in db.execute("SELECT id FROM users WHERE is_dept_admin=1 AND department_id=? "
                                     "AND is_active=1", (dept_id,))]
    return ids


# ---------------------------------------------------------------- sorting and filtering lists
def sort_clause(db, sort, direction):
    """(ORDER BY text, params). sort = updated | created | col:<column name>."""
    d = "ASC" if direction == "asc" else "DESC"
    if sort == "created":
        return f"r.created_at {d}, r.id {d}", []
    if (sort or "").startswith("col:"):
        name = sort[4:]
        numeric = db.execute("SELECT 1 FROM columns WHERE lower(name)=lower(?) AND col_type='number' "
                             "AND removed_at IS NULL LIMIT 1", (name,)).fetchone()
        sub = ("(SELECT v.value FROM record_values v JOIN columns c ON c.id=v.column_id "
               "AND c.removed_at IS NULL WHERE v.record_id=r.id AND lower(c.name)=lower(?) LIMIT 1)")
        expr = f"CAST({sub} AS REAL)" if numeric else f"{sub} COLLATE NOCASE"
        return f"({sub} IS NULL), {expr} {d}, r.id DESC", [name, name]
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
    if user["role"] == "admin":
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


def public_view(db, rec, fields):
    """[(label, value)] of one record, only the chosen fields and only the filled ones."""
    vals = values_for(db, [rec["id"]])[rec["id"]]
    out = []
    for c in get_columns(db, rec["department_id"]):
        if c["name"].lower() in fields and vals.get(c["id"]):
            out.append((c["name"], vals[c["id"]]))
    return out


# ---------------------------------------------------------------- transfers
def create_transfer(db, user, rec, to_id, note, immediately=False):
    """Hand a record over to another user. Returns an error text or None."""
    target = db.execute("SELECT * FROM users WHERE id=? AND is_active=1", (to_id,)).fetchone()
    if target is None:
        return "Choose a user."
    if target["id"] == rec["owner_id"]:
        return "That user already owns this record."
    if db.execute("SELECT 1 FROM transfers WHERE record_id=? AND status='pending'", (rec["id"],)).fetchone():
        return "A handover of this record is already waiting for an answer."
    tid = db.execute("INSERT INTO transfers(record_id,from_user,to_user,note) VALUES (?,?,?,?)",
                     (rec["id"], rec["owner_id"], target["id"], (note or "")[:300])).lastrowid
    add_history(db, rec["id"], user, "transfer_requested", new=target["full_name"])
    if immediately:
        resolve_transfer(db, user, db.execute("SELECT * FROM transfers WHERE id=?", (tid,)).fetchone(), "accept")
    else:
        notify(db, [target["id"]], f"{user['full_name']} wants to hand over a record to you.", "/transfers", skip=user["id"])
    return None


def resolve_transfer(db, user, tr, action):
    """accept / decline (by the receiver) or cancel (by the sender or an admin)."""
    status = {"accept": "accepted", "decline": "declined", "cancel": "cancelled"}[action]
    db.execute("UPDATE transfers SET status=?, resolved_at=datetime('now','localtime') WHERE id=?", (status, tr["id"]))
    names = {r["id"]: r["full_name"] for r in db.execute(
        "SELECT id, full_name FROM users WHERE id IN (?,?)", (tr["from_user"], tr["to_user"]))}
    if action == "accept":
        db.execute("UPDATE records SET owner_id=?, version=version+1, updated_at=datetime('now','localtime') WHERE id=?",
                   (tr["to_user"], tr["record_id"]))
        add_history(db, tr["record_id"], user, "transferred", names.get(tr["from_user"]), names.get(tr["to_user"]))
    else:
        add_history(db, tr["record_id"], user, "transfer_" + status)
    other = tr["from_user"] if user["id"] == tr["to_user"] else tr["to_user"]
    notify(db, [other], f"Handover {status} by {user['full_name']}.", f"/records/{tr['record_id']}", skip=user["id"])
