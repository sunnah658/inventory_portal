"""
routes_admin.py - everything only the admin can do.

Used by: app.py (registers it).
Uses:    auth.py, core.py, models.py, import_users.py, backup.py, branding.py, config.py
Pages:   dashboard, all records, users, departments, record columns, import users,
         activity log, settings (company name and logo).
"""
import csv
import io
import os
import sqlite3
from datetime import date, timedelta

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import generate_password_hash

import config
from auth import admin_required
from backup import make_backup
from core import (COLUMN_TYPES, TYPE_LABEL, build_csv, column_names, create_department, get_columns,
                  rec_select, reminder_rows, search_clause, summaries_for, table_context)
from import_users import import_users
from models import get_db, log, setting_get, setting_set
from routes_records import label_items, list_options
from security import password_problem, reauth_ok, revoke_session, revoke_user_sessions
from templates_data import TEMPLATES
from utils import csv_response, generate_password, like_pattern, page_info

bp = Blueprint("admin", __name__, url_prefix="/admin")

DONUT_COLORS = ["#17a05d", "#0b6e99", "#e8a317", "#d9534f", "#7b61c4", "#9db3c1"]


def _departments():
    return get_db().execute("SELECT id, name FROM departments ORDER BY name").fetchall()


def _confirmed():
    """Dangerous actions need the admin's own password (see security.reauth_ok)."""
    if reauth_ok(g.user, request.form):
        return True
    flash("Type your password to confirm this action.", "error")
    return False


# ================================================================ dashboard
@bp.route("/dashboard")
@admin_required
def dashboard():
    db = get_db()
    today = date.today()
    soon = reminder_rows(db, g.user, today.isoformat(),
                         (today + timedelta(days=config.REMINDER_DAYS)).isoformat(), limit=100)
    sums = summaries_for(db, soon[:6])
    stats = {
        "records": db.execute("SELECT COUNT(*) FROM records WHERE deleted_at IS NULL").fetchone()[0],
        "new_week": db.execute("SELECT COUNT(*) FROM records WHERE deleted_at IS NULL AND "
                               "created_at >= datetime('now','localtime','-7 days')").fetchone()[0],
        "users": db.execute("SELECT COUNT(*) FROM users WHERE is_active=1").fetchone()[0],
        "disabled": db.execute("SELECT COUNT(*) FROM users WHERE is_active=0").fetchone()[0],
        "repairs": db.execute("SELECT COUNT(*) FROM repairs p JOIN records r ON r.id=p.record_id "
                              "WHERE p.date_back IS NULL AND r.deleted_at IS NULL").fetchone()[0],
        "soon": len(soon),
        "bin": db.execute("SELECT COUNT(*) FROM records WHERE deleted_at IS NOT NULL").fetchone()[0],
        "requests": db.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0],
        "transfers": db.execute("SELECT COUNT(*) FROM transfers WHERE status='pending'").fetchone()[0],
        "sessions": db.execute("SELECT COUNT(*) FROM sessions WHERE revoked=0 AND last_seen > "
                               "datetime('now','localtime',?)", (f"-{config.IDLE_MINUTES} minutes",)).fetchone()[0],
    }
    by_dept = db.execute("SELECT d.name, COUNT(r.id) AS n FROM departments d LEFT JOIN records r "
                         "ON r.department_id=d.id AND r.deleted_at IS NULL GROUP BY d.id "
                         "ORDER BY n DESC, d.name").fetchall()
    status = db.execute(
        "SELECT v.value AS label, COUNT(*) AS n FROM record_values v "
        "JOIN columns c ON c.id=v.column_id AND c.removed_at IS NULL AND lower(c.name)='status' "
        "JOIN records r ON r.id=v.record_id AND r.deleted_at IS NULL "
        "GROUP BY v.value ORDER BY n DESC LIMIT 6").fetchall()
    total_status = sum(s["n"] for s in status)
    donut, start = [], 0.0
    for i, s in enumerate(status):                       # CSS conic-gradient for the donut chart
        end = start + 100.0 * s["n"] / total_status
        donut.append(f"{DONUT_COLORS[i]} {start:.2f}% {end:.2f}%")
        start = end
    return render_template(
        "admin_dashboard.html", stats=stats, by_dept=by_dept, max_dept=max([d["n"] for d in by_dept] + [1]),
        status=status, total_status=total_status, colors=DONUT_COLORS,
        donut_css="conic-gradient(" + ", ".join(donut) + ")" if donut else "",
        soon=[dict(r, summary=sums[r["id"]]) for r in soon[:6]],
        recent=db.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT 6").fetchall())


# ================================================================ all records
def _record_filters():
    """Read the filters and sorting of the all-records page.
    Returns (where, params, q, dept, owner, order_by, order_params, info)."""
    db = get_db()
    q = (request.args.get("q") or "").strip()
    dept = request.args.get("department", "")
    owner = request.args.get("owner", "")
    sq, sp = search_clause(q)
    fq, order, fp, op, info = list_options(db, g.user, request.args)
    where, params = "r.deleted_at IS NULL" + sq + fq, list(sp) + list(fp)
    if dept.isdigit():
        where += " AND r.department_id=?"
        params.append(int(dept))
    if owner.isdigit():
        where += " AND r.owner_id=?"
        params.append(int(owner))
    return where, params, q, dept, owner, order, op, info


@bp.route("/records")
@admin_required
def all_records():
    db = get_db()
    where, params, q, dept, owner, order, op, info = _record_filters()
    total = db.execute("SELECT COUNT(*) FROM records r WHERE " + where, params).fetchone()[0]
    page, pages, offset = page_info(total, request.args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute(rec_select() + " WHERE " + where + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                      params + op + [config.PER_PAGE, offset]).fetchall()
    # One department selected: show its full columns. Otherwise a short summary table.
    full = table_context(db, rows, g.user) if dept.isdigit() else None
    sums = None if full else summaries_for(db, rows)
    return render_template("admin_records.html", rows=rows, full=full, sums=sums, q=q, dept=dept,
                           owner=owner, total=total, page=page, pages=pages, info=info,
                           names=column_names(db, g.user), view_page="admin_records",
                           keep={k: v for k, v in request.args.items() if k != "page"},
                           saved=db.execute("SELECT * FROM saved_views WHERE user_id=? AND page='admin_records' "
                                            "ORDER BY name", (g.user["id"],)).fetchall(),
                           departments=_departments(),
                           people=db.execute("SELECT id, full_name, username FROM users "
                                             "ORDER BY full_name").fetchall())


@bp.route("/records/download")
@admin_required
def all_records_download():
    db = get_db()
    where, params, _q, dept, _owner, _order, _op, _info = _record_filters()
    rows = db.execute(rec_select() + " WHERE " + where + " ORDER BY d.name, u.full_name, r.id",
                      params).fetchall()
    header, out = build_csv(db, rows, with_owner=True)
    name = "all_records"
    if dept.isdigit():
        d = db.execute("SELECT name FROM departments WHERE id=?", (int(dept),)).fetchone()
        name = "records_" + d["name"] if d else name
    log(db, "download_csv", f"{len(rows)} records ({name})")
    db.commit()
    return csv_response(header, out, name)


@bp.route("/labels")
@admin_required
def labels():
    """Printable QR labels for one department (up to 300 records)."""
    db = get_db()
    dept = request.args.get("department", "")
    if not dept.isdigit():
        flash("Choose a department first, then print its labels.", "error")
        return redirect(url_for("admin.all_records"))
    rows = db.execute(rec_select() + " WHERE r.deleted_at IS NULL AND r.department_id=? "
                      "ORDER BY r.id LIMIT 300", (int(dept),)).fetchall()
    return render_template("qr_label.html", items=label_items(db, rows), many=True)


# ================================================================ users
def _save_view_departments(db, user_id, chosen, own_dept):
    """Departments this user may view (and suggest changes for), besides their own."""
    valid = {r[0] for r in db.execute("SELECT id FROM departments")}
    wanted = {int(x) for x in chosen if str(x).isdigit() and int(x) in valid and int(x) != own_dept}
    db.execute("DELETE FROM user_view_departments WHERE user_id=?", (user_id,))
    for d in wanted:
        db.execute("INSERT INTO user_view_departments(user_id,department_id) VALUES (?,?)", (user_id, d))


@bp.route("/users")
@admin_required
def users():
    q = (request.args.get("q") or "").strip()
    sql = ("SELECT u.*, d.name AS department_name, (SELECT COUNT(*) FROM records r "
           "WHERE r.owner_id=u.id AND r.deleted_at IS NULL) AS item_count "
           "FROM users u LEFT JOIN departments d ON d.id=u.department_id")
    params = []
    if q:
        sql += (" WHERE u.full_name LIKE ? ESCAPE '\\' OR u.username LIKE ? ESCAPE '\\'"
                " OR d.name LIKE ? ESCAPE '\\'")
        params = [like_pattern(q)] * 3
    rows = get_db().execute(sql + " ORDER BY u.full_name", params).fetchall()
    return render_template("admin_users.html", rows=rows, q=q)


@bp.route("/users/add", methods=["GET", "POST"])
@admin_required
def user_add():
    departments = _departments()
    if not departments:
        flash("Add a department first.", "error")
        return redirect(url_for("admin.departments"))
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        full_name = (form.get("full_name") or "").strip()
        username = (form.get("username") or "").strip()
        dept = form.get("department_id") or ""
        role = form.get("role") or "user"
        password = (form.get("password") or "").strip()
        db = get_db()
        error = None
        if not full_name or not username or not dept.isdigit():
            error = "Full name, username and department are required."
        elif role not in ("user", "admin"):
            error = "Role must be user or admin."
        elif password and password_problem(password, username):
            error = password_problem(password, username)
        elif db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            error = f"The username '{username}' is already used."
        if error:
            flash(error, "error")
        else:
            password = password or generate_password()
            uid = db.execute("INSERT INTO users(full_name,username,password_hash,department_id,role,"
                             "must_change_password,is_dept_admin) VALUES (?,?,?,?,?,1,?)",
                             (full_name, username, generate_password_hash(password), int(dept), role,
                              1 if form.get("is_dept_admin") else 0)).lastrowid
            _save_view_departments(db, uid, form.getlist("view_dept"), int(dept))
            log(db, "user_add", username)
            db.commit()
            flash(f"User created. Temporary password for {username}: {password}", "secret")
            return redirect(url_for("admin.users"))
    return render_template("admin_user_form.html", item=form, departments=departments, editing=False,
                           view_ids=set())


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        dept = request.form.get("department_id") or ""
        role = request.form.get("role") or "user"
        active = 1 if request.form.get("is_active") else 0
        error = None
        if not full_name or not dept.isdigit():
            error = "Full name and department are required."
        elif role not in ("user", "admin"):
            error = "Role must be user or admin."
        elif row["id"] == g.user["id"] and (role != "admin" or not active):
            error = "You cannot remove your own admin access or disable yourself."
        elif (role != row["role"] or (row["is_active"] and not active)) and not _confirmed():
            error = "Changing a role or disabling an account needs your password."
        if error:
            flash(error, "error")
        else:
            # Records stay in the department they were created in.
            db.execute("UPDATE users SET full_name=?, department_id=?, role=?, is_active=?, is_dept_admin=? WHERE id=?",
                       (full_name, int(dept), role, active, 1 if request.form.get("is_dept_admin") else 0, user_id))
            _save_view_departments(db, user_id, request.form.getlist("view_dept"), int(dept))
            if not active:
                revoke_user_sessions(db, user_id)             # a disabled user is logged out at once
            log(db, "user_edit", row["username"])
            db.commit()
            flash("User updated.", "ok")
            return redirect(url_for("admin.users"))
    return render_template("admin_user_form.html", item=dict(row), departments=_departments(), editing=True,
                           view_ids={r[0] for r in db.execute(
                               "SELECT department_id FROM user_view_departments WHERE user_id=?", (user_id,))})


@bp.route("/users/<int:user_id>/reset", methods=["POST"])
@admin_required
def user_reset(user_id):
    db = get_db()
    row = db.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        abort(404)
    if not _confirmed():
        return redirect(url_for("admin.users"))
    password = generate_password()
    revoke_user_sessions(db, user_id)
    db.execute("UPDATE users SET password_hash=?, must_change_password=1 WHERE id=?",
               (generate_password_hash(password), user_id))
    log(db, "password_reset", row["username"])
    db.commit()
    flash(f"New temporary password for {row['username']}: {password}", "secret")
    return redirect(url_for("admin.users"))


# ================================================================ departments
@bp.route("/departments", methods=["GET", "POST"])
@admin_required
def departments():
    db = get_db()
    if request.method == "POST":
        name = " ".join((request.form.get("name") or "").split())[:100]
        template = request.form.get("template", "")
        key = template if template in TEMPLATES else None
        selected = {int(x) for x in request.form.getlist("cols") if x.isdigit()} if key else None
        if not name:
            flash("Type the department name.", "error")
        else:
            try:
                dept_id = create_department(db, name, key, selected)
                log(db, "department_add", name)
                db.commit()
                flash(f"Department '{name}' created. Check its columns below.", "ok")
                return redirect(url_for("admin.columns", did=dept_id))
            except sqlite3.IntegrityError:
                db.rollback()
                flash(f"The department '{name}' already exists.", "error")
        return redirect(url_for("admin.departments", template=template))
    template = request.args.get("template", "")
    rows = db.execute(
        "SELECT d.id, d.name, (SELECT COUNT(*) FROM users u WHERE u.department_id=d.id) AS user_count, "
        "(SELECT COUNT(*) FROM records r WHERE r.department_id=d.id AND r.deleted_at IS NULL) AS item_count, "
        "(SELECT COUNT(*) FROM columns c WHERE c.department_id=d.id AND c.removed_at IS NULL) AS col_count "
        "FROM departments d ORDER BY d.name").fetchall()
    return render_template("admin_departments.html", rows=rows, templates=TEMPLATES,
                           template=template if template in TEMPLATES else "")


@bp.route("/departments/<int:did>/delete", methods=["POST"])
@admin_required
def department_delete(did):
    db = get_db()
    row = db.execute("SELECT name FROM departments WHERE id = ?", (did,)).fetchone()
    if row is None:
        abort(404)
    if not _confirmed():
        return redirect(url_for("admin.departments"))
    users = db.execute("SELECT COUNT(*) FROM users WHERE department_id=?", (did,)).fetchone()[0]
    items = db.execute("SELECT COUNT(*) FROM records WHERE department_id=?", (did,)).fetchone()[0]
    if users or items:
        flash(f"'{row['name']}' still has {users} user(s) and {items} record(s) "
              "(including the recycle bin). Move the users and erase the records first.", "error")
    else:
        db.execute("DELETE FROM departments WHERE id = ?", (did,))
        log(db, "department_delete", row["name"])
        db.commit()
        flash(f"Department '{row['name']}' removed.", "ok")
    return redirect(url_for("admin.departments"))


@bp.route("/departments/<int:did>/attachments", methods=["POST"])
@admin_required
def department_attachments(did):
    """Turn attachments on or off for a department and set the max file size."""
    db = get_db()
    row = db.execute("SELECT name FROM departments WHERE id=?", (did,)).fetchone()
    if row is None:
        abort(404)
    enabled = 1 if request.form.get("enabled") else 0
    size = min(max(request.form.get("max_mb", 10, type=int), 1), config.MAX_UPLOAD_MB)
    db.execute("UPDATE departments SET attachments_enabled=?, attachment_max_mb=? WHERE id=?",
               (enabled, size, did))
    log(db, "attachment_settings", f"{row['name']}: {'on' if enabled else 'off'}, {size} MB")
    db.commit()
    flash("Attachment settings saved.", "ok")
    return redirect(url_for("admin.columns", did=did))


# ================================================================ record columns
def _column(cid):
    col = get_db().execute("SELECT * FROM columns WHERE id=?", (cid,)).fetchone()
    if col is None:
        abort(404)
    return col


def _parse_options(text):
    return "\n".join(o.strip() for o in (text or "").replace("\r", "").split("\n") if o.strip())


@bp.route("/departments/<int:did>/columns")
@admin_required
def columns(did):
    db = get_db()
    dept = db.execute("SELECT * FROM departments WHERE id=?", (did,)).fetchone()
    if dept is None:
        abort(404)
    cols = db.execute("SELECT c.*, (SELECT COUNT(*) FROM record_values v WHERE v.column_id=c.id) AS used "
                      "FROM columns c WHERE c.department_id=? AND c.removed_at IS NULL "
                      "ORDER BY c.position, c.id", (did,)).fetchall()
    removed = db.execute("SELECT COUNT(*) FROM columns WHERE department_id=? AND removed_at IS NOT NULL",
                         (did,)).fetchone()[0]
    return render_template("admin_columns.html", dept=dept, cols=cols, removed=removed,
                           types=COLUMN_TYPES, type_label=TYPE_LABEL, server_max=config.MAX_UPLOAD_MB)


@bp.route("/departments/<int:did>/columns/add", methods=["POST"])
@admin_required
def column_add(did):
    db = get_db()
    if db.execute("SELECT 1 FROM departments WHERE id=?", (did,)).fetchone() is None:
        abort(404)
    name = " ".join((request.form.get("name") or "").split())[:60]
    ctype = request.form.get("col_type", "")
    options = _parse_options(request.form.get("options"))
    reminder = 1 if (request.form.get("is_reminder") and ctype == "date") else 0
    has_time = 1 if (request.form.get("has_time") and ctype == "date") else 0
    error = None
    if not name:
        error = "Type a column name."
    elif ctype not in TYPE_LABEL:
        error = "Choose a column type."
    elif ctype == "dropdown" and not options:
        error = "A dropdown column needs at least one option (one per line)."
    if error:
        flash(error, "error")
        return redirect(url_for("admin.columns", did=did))
    pos = db.execute("SELECT COALESCE(MAX(position),-1)+1 FROM columns WHERE department_id=?", (did,)).fetchone()[0]
    try:
        db.execute("INSERT INTO columns(department_id,name,col_type,options,required,protected,"
                   "is_reminder,has_time,position) VALUES (?,?,?,?,?,?,?,?,?)",
                   (did, name, ctype, options or None, 1 if request.form.get("required") else 0,
                    1 if request.form.get("protected") else 0, reminder, has_time, pos))
        log(db, "column_add", f"department {did}: {name}")
        db.commit()
        flash(f"Column '{name}' added. Existing records show it as blank.", "ok")
    except sqlite3.IntegrityError:
        db.rollback()
        flash(f"This department already has a column named '{name}'.", "error")
    return redirect(url_for("admin.columns", did=did))


@bp.route("/columns/<int:cid>/edit", methods=["GET", "POST"])
@admin_required
def column_edit(cid):
    col = _column(cid)
    db = get_db()
    if request.method == "POST":
        name = " ".join((request.form.get("name") or "").split())[:60]
        options = _parse_options(request.form.get("options")) if col["col_type"] == "dropdown" else None
        reminder = 1 if (request.form.get("is_reminder") and col["col_type"] == "date") else 0
        has_time = 1 if (request.form.get("has_time") and col["col_type"] == "date") else 0
        # Protection can be switched ON here. Switching it OFF needs the separate
        # "Remove protection" button, so it cannot happen by accident.
        protected = 1 if (col["protected"] or request.form.get("protected")) else 0
        if not name:
            flash("Type a column name.", "error")
        elif col["col_type"] == "dropdown" and not options:
            flash("A dropdown column needs at least one option.", "error")
        else:
            try:
                db.execute("UPDATE columns SET name=?, options=?, required=?, shown=?, protected=?,"
                           " is_reminder=?, has_time=? WHERE id=?",
                           (name, options, 1 if request.form.get("required") else 0,
                            1 if request.form.get("shown") else 0, protected, reminder, has_time, cid))
                log(db, "column_edit", f"{col['name']} -> {name}")
                db.commit()
                flash("Column saved.", "ok")
                return redirect(url_for("admin.columns", did=col["department_id"]))
            except sqlite3.IntegrityError:
                db.rollback()
                flash(f"This department already has a column named '{name}'.", "error")
    return render_template("admin_column_edit.html", col=col, type_label=TYPE_LABEL,
                           dept=db.execute("SELECT * FROM departments WHERE id=?",
                                           (col["department_id"],)).fetchone())


@bp.route("/columns/<int:cid>/move", methods=["POST"])
@admin_required
def column_move(cid):
    col = _column(cid)
    db = get_db()
    ids = [r["id"] for r in db.execute("SELECT id FROM columns WHERE department_id=? AND removed_at IS NULL "
                                       "ORDER BY position, id", (col["department_id"],))]
    i = ids.index(cid)
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
        for pos, one in enumerate(ids):               # renumber so the order is always clean
            db.execute("UPDATE columns SET position=? WHERE id=?", (pos, one))
        db.commit()
    return redirect(url_for("admin.columns", did=col["department_id"]))


@bp.route("/columns/<int:cid>/unprotect", methods=["POST"])
@admin_required
def column_unprotect(cid):
    col = _column(cid)
    db = get_db()
    if not _confirmed():
        return redirect(url_for("admin.columns", did=col["department_id"]))
    db.execute("UPDATE columns SET protected=0 WHERE id=?", (cid,))
    log(db, "column_unprotect", col["name"])
    db.commit()
    flash(f"Protection removed from '{col['name']}'. It can be removed now.", "ok")
    return redirect(url_for("admin.columns", did=col["department_id"]))


@bp.route("/columns/<int:cid>/remove", methods=["POST"])
@admin_required
def column_remove(cid):
    """Step 1: hide the column. Its data is kept in 'Removed columns'."""
    col = _column(cid)
    db = get_db()
    if col["protected"]:
        flash(f"'{col['name']}' is protected. Remove the protection first.", "error")
    elif (request.form.get("confirm_name") or "").strip().lower() != col["name"].lower():
        flash("The name you typed does not match, so nothing was removed.", "error")
    elif not _confirmed():
        pass
    else:
        db.execute("UPDATE columns SET removed_at=datetime('now','localtime'), is_reminder=0 WHERE id=?", (cid,))
        log(db, "column_remove", col["name"])
        db.commit()
        flash(f"Column '{col['name']}' removed. Its data is kept; you can restore it any time.", "ok")
    return redirect(url_for("admin.columns", did=col["department_id"]))


@bp.route("/departments/<int:did>/removed")
@admin_required
def removed_columns(did):
    db = get_db()
    dept = db.execute("SELECT * FROM departments WHERE id=?", (did,)).fetchone()
    if dept is None:
        abort(404)
    cols = db.execute("SELECT c.*, (SELECT COUNT(*) FROM record_values v WHERE v.column_id=c.id) AS used "
                      "FROM columns c WHERE c.department_id=? AND c.removed_at IS NOT NULL "
                      "ORDER BY c.removed_at DESC", (did,)).fetchall()
    return render_template("admin_removed_columns.html", dept=dept, cols=cols, type_label=TYPE_LABEL)


@bp.route("/columns/<int:cid>/restore", methods=["POST"])
@admin_required
def column_restore(cid):
    col = _column(cid)
    db = get_db()
    try:
        db.execute("UPDATE columns SET removed_at=NULL WHERE id=?", (cid,))
        log(db, "column_restore", col["name"])
        db.commit()
        flash(f"Column '{col['name']}' is back with all its data.", "ok")
    except sqlite3.IntegrityError:
        db.rollback()
        flash(f"Cannot restore: the department already has a column named '{col['name']}'. "
              "Rename that one first.", "error")
    return redirect(url_for("admin.removed_columns", did=col["department_id"]))


@bp.route("/columns/<int:cid>/erase", methods=["POST"])
@admin_required
def column_erase(cid):
    """Step 2: erase a removed column and its data for good (after an automatic backup)."""
    col = _column(cid)
    db = get_db()
    if not col["removed_at"]:
        abort(400)
    if (request.form.get("confirm_name") or "").strip().lower() != col["name"].lower():
        flash("The name you typed does not match, so nothing was erased.", "error")
    elif not _confirmed():
        pass
    else:
        backup_file = make_backup("before-erase_")      # safety copy first
        db.execute("DELETE FROM columns WHERE id=?", (cid,))   # its values go with it (CASCADE)
        log(db, "column_erase", f"{col['name']} (backup {os.path.basename(backup_file)})")
        db.commit()
        flash(f"Column '{col['name']}' erased for good. A backup was saved first: "
              f"{os.path.basename(backup_file)}.", "ok")
    return redirect(url_for("admin.removed_columns", did=col["department_id"]))


# ================================================================ import, activity, settings
@bp.route("/import", methods=["GET", "POST"])
@admin_required
def import_page():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Choose a CSV file first.", "error")
            return render_template("admin_import.html")
        raw = file.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            flash("The file is larger than 1 MB.", "error")
            return render_template("admin_import.html")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Save the file as CSV UTF-8 and try again.", "error")
            return render_template("admin_import.html")
        db = get_db()
        created, skipped = import_users(db, text)
        log(db, "user_import", f"{len(created)} created, {len(skipped)} skipped")
        db.commit()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["full_name", "username", "department", "role", "temporary_password"])
        for c in created:
            writer.writerow([c["full_name"], c["username"], c["department"], c["role"], c["password"]])
        return render_template("admin_import_result.html", created=created, skipped=skipped,
                               credentials_csv=out.getvalue())
    return render_template("admin_import.html")


@bp.route("/activity")
@admin_required
def activity():
    q = (request.args.get("q") or "").strip()
    sql, params = "SELECT * FROM activity_log", []
    if q:
        sql += (" WHERE username LIKE ? ESCAPE '\\' OR action LIKE ? ESCAPE '\\' OR details LIKE ? ESCAPE '\\'"
                " OR ip LIKE ? ESCAPE '\\'")
        params = [like_pattern(q)] * 4
    rows = get_db().execute(sql + " ORDER BY id DESC LIMIT 300", params).fetchall()
    return render_template("admin_activity.html", rows=rows, q=q, keep_days=config.ACTIVITY_KEEP_DAYS)


@bp.route("/sessions")
@admin_required
def sessions():
    """Who is logged in right now, from which computer. The admin can end a session."""
    rows = get_db().execute(
        "SELECT s.*, u.full_name, u.username FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.revoked=0 AND s.last_seen > datetime('now','localtime',?) ORDER BY s.last_seen DESC",
        (f"-{config.IDLE_MINUTES} minutes",)).fetchall()
    return render_template("admin_sessions.html", rows=rows, current=session.get("sid"))


@bp.route("/sessions/<sid>/end", methods=["POST"])
@admin_required
def session_end(sid):
    db = get_db()
    revoke_session(db, sid)
    log(db, "session_end", sid[:8])
    db.commit()
    flash("That session was ended.", "ok")
    return redirect(url_for("admin.sessions"))


def _image_type(data):
    """Recognise PNG, JPEG and WEBP by their first bytes (the file name is not trusted)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _remove_custom_logo():
    for ext in config.LOGO_EXTENSIONS:
        path = os.path.join(config.BRAND_DIR, "logo." + ext)
        if os.path.exists(path):
            os.remove(path)


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "name":
            name = " ".join((request.form.get("company_name") or "").split())[:100]
            if name:
                setting_set(db, "company_name", name)
                log(db, "settings", "company name changed")
                db.commit()
                flash("Company name saved.", "ok")
            else:
                flash("Type the company name.", "error")
        elif action == "logo":
            file = request.files.get("logo")
            raw = file.read(2 * 1024 * 1024 + 1) if file and file.filename else b""
            kind = _image_type(raw[:16]) if raw else None
            if not raw:
                flash("Choose a logo file first.", "error")
            elif len(raw) > 2 * 1024 * 1024:
                flash("The logo is larger than 2 MB.", "error")
            elif kind is None:
                flash("The logo must be a PNG, JPG or WEBP picture.", "error")
            else:
                _remove_custom_logo()
                with open(os.path.join(config.BRAND_DIR, "logo." + kind), "wb") as fh:
                    fh.write(raw)
                log(db, "settings", "logo changed")
                db.commit()
                flash("Logo changed. It shows on every page, the login page and the browser tab.", "ok")
        elif action == "reset_logo":
            _remove_custom_logo()
            log(db, "settings", "logo reset to default")
            db.commit()
            flash("The default logo is back.", "ok")
        return redirect(url_for("admin.settings"))
    return render_template("admin_settings.html",
                           name=setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME))
