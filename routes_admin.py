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
from auth import admin_required, login_required
from utils import is_portal_admin, is_true_admin
from backup import make_backup
from core import (COLUMN_TYPES, TYPE_LABEL, admin_ids, build_csv, column_names, create_department, get_columns,
                  notify, rec_select, reminder_rows, search_clause, summaries_for, table_context)
from import_users import import_users
from models import get_db, log, setting_get, setting_set
from routes_records import code_redirect, list_options
from security import password_problem, reauth_ok, revoke_session, revoke_user_sessions
from templates_data import TEMPLATES
from utils import csv_response, generate_password, like_pattern, page_info

bp = Blueprint("admin", __name__, url_prefix="/admin")

DONUT_COLORS = ["#17a05d", "#0b6e99", "#e8a317", "#d9534f", "#7b61c4", "#9db3c1"]


def _departments():
    return get_db().execute("SELECT id, name FROM departments ORDER BY name").fetchall()


def _save_view_departments(db, uid, view_dept, own_dept):
    """Save the extra departments a user may view (besides his own). Needed by
    user_add / user_edit; the view_dept checkboxes on the user form feed it."""
    db.execute("DELETE FROM user_view_departments WHERE user_id=?", (uid,))
    for did in view_dept or []:
        if str(did).isdigit() and int(did) != own_dept:
            db.execute("INSERT OR IGNORE INTO user_view_departments(user_id, department_id) VALUES (?,?)",
                       (uid, int(did)))


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
        "disabled": db.execute("SELECT COUNT(*) FROM users WHERE is_active=0 AND is_deleted=0").fetchone()[0],
        "repairs": db.execute("SELECT COUNT(*) FROM repairs p JOIN records r ON r.id=p.record_id "
                              "WHERE p.date_back IS NULL AND r.deleted_at IS NULL").fetchone()[0],
        "soon": len(soon),
        "bin": db.execute("SELECT COUNT(*) FROM records WHERE deleted_at IS NOT NULL").fetchone()[0],
        "repairs_on": db.execute("SELECT COUNT(*) FROM departments WHERE repairs_enabled=1").fetchone()[0],
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
    code_page = code_redirect(request.args.get("q"))          # typing HRC-12 opens that QR code
    if code_page:
        return code_page
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
                           names=column_names(db, g.user),
                           keep={k: v for k, v in request.args.items() if k != "page"},
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


@bp.route("/users")
@admin_required
def users():
    """All users (not deleted ones: those live in the Recycle Bin Users tab).
    Filters, all combinable with the search: department, one specific user,
    role (Admin / Department admin / User) and status (Active / Locked / Pending approval)."""
    db = get_db()
    q = (request.args.get("q") or "").strip()
    dept = request.args.get("department", "")
    user_filter = request.args.get("user", "")
    role_filter = request.args.get("role", "")
    status_filter = request.args.get("status", "")
    sql = ("SELECT u.*, d.name AS department_name, (SELECT COUNT(*) FROM records r "
           "WHERE r.owner_id=u.id AND r.deleted_at IS NULL) AS item_count "
           "FROM users u LEFT JOIN departments d ON d.id=u.department_id")
    where = ["u.is_deleted=0"]
    params = []
    if q:
        where.append("(u.full_name LIKE ? ESCAPE '\\' OR u.username LIKE ? ESCAPE '\\'"
                     " OR d.name LIKE ? ESCAPE '\\')")
        params += [like_pattern(q)] * 3
    if dept.isdigit():
        where.append("u.department_id=?")
        params.append(int(dept))
    if user_filter.isdigit():
        where.append("u.id=?")
        params.append(int(user_filter))
    if role_filter == "admin":
        where.append("u.role='admin'")
    elif role_filter == "dept_admin":
        where.append("u.is_dept_admin=1")
    elif role_filter == "user":
        where.append("u.role='user' AND u.is_dept_admin=0")
    if status_filter == "active":
        where.append("u.is_active=1 AND u.approval_status != 'pending'")
    elif status_filter == "locked":
        where.append("u.is_active=0 AND u.approval_status != 'pending'")
    elif status_filter == "pending":
        where.append("u.approval_status='pending'")
    rows = db.execute(sql + " WHERE " + " AND ".join(where) + " ORDER BY u.full_name", params).fetchall()
    return render_template("admin_users.html", rows=rows, q=q, dept=dept, user_filter=user_filter,
                           role_filter=role_filter, status_filter=status_filter,
                           departments=_departments(),
                           people=db.execute("SELECT id, full_name, username FROM users "
                                             "WHERE is_deleted=0 ORDER BY full_name").fetchall(),
                           keep={k: v for k, v in request.args.items()})


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
        elif role == "admin" and not is_true_admin(g.user):
            error = "Only the original portal admin can create an admin account."
        elif password and password_problem(password, username):
            error = password_problem(password, username)
        elif db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            error = f"The username '{username}' is already used."
        if error:
            flash(error, "error")
        else:
            password = password or generate_password()
            uid = db.execute("INSERT INTO users(full_name,username,password_hash,department_id,role,"
                             "must_change_password,is_dept_admin,can_ddb_attachment,can_portal_admin,created_by) VALUES (?,?,?,?,?,1,?,?,?,?)",
                             (full_name, username, generate_password_hash(password), int(dept), role,
                              1 if form.get("is_dept_admin") else 0, 1 if form.get("can_ddb_attachment") else 0,
                              1 if (is_true_admin(g.user) and form.get("can_portal_admin")) else 0, g.user["id"])).lastrowid
            _save_view_departments(db, uid, form.getlist("view_dept"), int(dept))
            log(db, "user_add", username)
            db.commit()
            flash(f"User created. Temporary password for {username}: {password}", "secret")
            return redirect(url_for("admin.users"))
    return render_template("admin_user_form.html", item=form, departments=departments, editing=False,
                           view_ids=set(), can_grant_portal_admin=is_true_admin(g.user))


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["is_deleted"]:
        abort(404)
    # A permission user cannot edit (and so cannot disable or remove) a true portal admin.
    if not is_true_admin(g.user) and is_true_admin(row):
        abort(403)
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        username = (request.form.get("username") or "").strip()
        dept = request.form.get("department_id") or ""
        role = request.form.get("role") or "user"
        active = 1 if request.form.get("is_active") else 0
        error = None
        if not full_name or not username or not dept.isdigit():
            error = "Full name, username and department are required."
        elif db.execute("SELECT 1 FROM users WHERE username=? AND id != ?", (username, user_id)).fetchone():
            error = f"The username '{username}' is already used."
        elif role not in ("user", "admin"):
            error = "Role must be user or admin."
        elif role == "admin" and not is_true_admin(g.user):
            error = "Only the original portal admin can make someone an admin."
        elif row["id"] == g.user["id"] and (not active or (is_true_admin(g.user) and role != "admin")):
            # A true admin cannot remove his own admin role or disable himself.
            # A permission user has role "user" with can_portal_admin kept
            # separately (see new_permission below), so editing himself with
            # role "user" and active on must not be blocked here.
            error = "You cannot remove your own admin access or disable yourself."
        elif (role != row["role"] or (row["is_active"] and not active)) and not _confirmed():
            error = "Changing a role or disabling an account needs your password."
        if error:
            flash(error, "error")
        else:
            # A pending (dept-admin-created) account stays pending until it is approved
            # on the Users page; editing it here must not activate it by accident.
            if row["approval_status"] == "pending":
                active = 0
            # Portal administrative permission is granted only by the original portal
            # admin; anyone else editing a user leaves the existing value untouched.
            new_permission = (1 if request.form.get("can_portal_admin") else 0) if is_true_admin(g.user) else row["can_portal_admin"]
            # Records stay in the department they were created in.
            db.execute("UPDATE users SET full_name=?, username=?, department_id=?, role=?, is_active=?, is_dept_admin=?, can_ddb_attachment=?, can_portal_admin=? WHERE id=?",
                       (full_name, username, int(dept), role, active, 1 if request.form.get("is_dept_admin") else 0, 1 if request.form.get("can_ddb_attachment") else 0, new_permission, user_id))
            _save_view_departments(db, user_id, request.form.getlist("view_dept"), int(dept))
            if not active:
                revoke_user_sessions(db, user_id)             # a disabled user is logged out at once
            log(db, "user_edit", username)
            db.commit()
            flash("User updated.", "ok")
            return redirect(url_for("admin.users"))
    return render_template("admin_user_form.html", item=dict(row), departments=_departments(), editing=True,
                           view_ids={r[0] for r in db.execute(
                               "SELECT department_id FROM user_view_departments WHERE user_id=?", (user_id,))},
                           can_grant_portal_admin=is_true_admin(g.user))


@bp.route("/users/<int:user_id>/reset", methods=["POST"])
@admin_required
def user_reset(user_id):
    db = get_db()
    row = db.execute("SELECT username, role, is_deleted FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["is_deleted"]:
        abort(404)
    if not is_true_admin(g.user) and is_true_admin(row):
        abort(403)
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


# ================================================================ deptdb attachment access (portal admin only)
@bp.route("/ddb-attachment-access", methods=["GET", "POST"])
@admin_required
def ddb_attachment_access():
    """Portal admin gives (or removes) attachment-column access for dept admins."""
    db = get_db()
    if request.method == "POST":
        rows = db.execute("SELECT id FROM users WHERE is_dept_admin=1 AND is_active=1").fetchall()
        for r in rows:
            db.execute("UPDATE users SET can_ddb_attachment=? WHERE id=?",
                       (1 if request.form.get(f"allow_{r['id']}") else 0, r["id"]))
        log(db, "ddb_attachment_access", "portal admin updated dept-admin attachment access")
        db.commit()
        flash("Attachment-column access saved.", "ok")
        return redirect(url_for("admin.ddb_attachment_access"))
    rows = db.execute("SELECT u.*, d.name AS department_name FROM users u LEFT JOIN departments d ON d.id=u.department_id "
                      "WHERE u.is_dept_admin=1 AND u.is_active=1 ORDER BY d.name, u.full_name").fetchall()
    return render_template("admin_ddb_attachment.html", rows=rows)


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


@bp.route("/departments/<int:did>/repairs", methods=["POST"])
@admin_required
def department_repairs(did):
    """Turn the repair log on or off for a department (not every department needs it)."""
    db = get_db()
    row = db.execute("SELECT name FROM departments WHERE id=?", (did,)).fetchone()
    if row is None:
        abort(404)
    enabled = 1 if request.form.get("enabled") else 0
    db.execute("UPDATE departments SET repairs_enabled=? WHERE id=?", (enabled, did))
    log(db, "repair_log_setting", f"{row['name']}: {'on' if enabled else 'off'}")
    db.commit()
    flash("The repair log is " + ("ON" if enabled else "OFF (entries are kept, only hidden)") + " for this department.", "ok")
    return redirect(url_for("admin.columns", did=did))


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


# ================================================================ delete / approve / reject a user
@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id):
    """Soft-delete an account: it goes to the Recycle Bin Users tab for 30 days,
    its work stays (name in red) and can be restored. Only the portal admin and
    a portal-administrative-permission user can delete an account at all, and a
    permission user cannot delete a true portal admin (or himself)."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["is_deleted"]:
        abort(404)
    if user_id == g.user["id"]:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.users"))
    if not is_true_admin(g.user) and is_true_admin(row):
        abort(403)
    if not _confirmed():
        return redirect(url_for("admin.users"))
    db.execute("UPDATE users SET is_deleted=1, deleted_at=datetime('now','localtime'), deleted_by=?, "
               "is_active=0, bin_purged=0 WHERE id=?", (g.user["id"], user_id))
    revoke_user_sessions(db, user_id)
    log(db, "user_delete", row["username"])
    db.commit()
    flash(f"{row['full_name']} was moved to the Recycle Bin (Users tab). Their work stays for 30 days and can be restored.", "ok")
    return redirect(url_for("admin.users"))


def _approval_notify_targets(db, row):
    """Who should hear the outcome of a pending account: the dept admin who
    created it (recorded in created_by), or, for accounts created before
    that was recorded, the dept admins of the account's department."""
    if row["created_by"]:
        return [row["created_by"]]
    return [r[0] for r in db.execute(
        "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1",
        (row["department_id"],)).fetchall()]


@bp.route("/users/<int:user_id>/approve", methods=["POST"])
@admin_required
def user_approve(user_id):
    """Approve a dept-admin-created account: it becomes functional at once."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["is_deleted"] or row["approval_status"] != "pending":
        abort(404)
    db.execute("UPDATE users SET approval_status='approved', is_active=1 WHERE id=?", (user_id,))
    log(db, "user_approve", row["username"])
    # The dept admin who created the account hears that it was approved
    # (2026-11-05): tapping the notification opens their own Users page
    # at the approved account (the portal Users page is not theirs to open).
    notify(db, _approval_notify_targets(db, row),
           f"Your account for {row['full_name']} was approved by {g.user['full_name']} and can now log in.",
           f"/admin/dept-users#user-{user_id}", skip=g.user["id"])
    db.commit()
    flash(f"{row['full_name']} is approved and can now log in.", "ok")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/reject", methods=["POST"])
@admin_required
def user_reject(user_id):
    """Reject a dept-admin-created account: it never became functional, so it is
    removed outright (it never appears in the Recycle Bin)."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["is_deleted"] or row["approval_status"] != "pending":
        abort(404)
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    log(db, "user_reject", row["username"])
    notify(db, _approval_notify_targets(db, row),
           f"Your account for {row['full_name']} was rejected by {g.user['full_name']}.",
           "/admin/dept-users", skip=g.user["id"])
    db.commit()
    flash(f"The pending account for {row['full_name']} was rejected and removed.", "ok")
    return redirect(url_for("admin.users"))


# ================================================================ department admin Users page
def _dept_users_dept():
    """The department a dept-admin Users page covers: a dept admin's own
    department only; a portal admin may pick one with ?dept=."""
    db = get_db()
    if is_portal_admin(g.user):
        dept_id = request.args.get("dept", type=int) or g.user["department_id"]
    else:
        dept_id = g.user["department_id"]
    dept = db.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone() if dept_id else None
    if dept is None:
        abort(403)
    return db, dept


@bp.route("/dept-users")
@login_required
def dept_users():
    """Department admin Users page: view the accounts of his own department and
    create an account for his own department. No reset, lock, disable, edit or
    delete buttons exist here at all — those are portal-admin actions."""
    db, dept = _dept_users_dept()
    if not (g.user["is_dept_admin"] or is_portal_admin(g.user)):
        abort(403)
    rows = db.execute("SELECT u.*, (SELECT COUNT(*) FROM records r WHERE r.owner_id=u.id AND r.deleted_at IS NULL) AS item_count "
                      "FROM users u WHERE u.department_id=? AND u.is_deleted=0 ORDER BY u.full_name", (dept["id"],)).fetchall()
    return render_template("dept_users.html", dept=dept, rows=rows,
                           departments=_departments() if is_portal_admin(g.user) else [])


@bp.route("/dept-users/add", methods=["GET", "POST"])
@login_required
def dept_user_add():
    """Create an account for the dept admin's own department. It stays pending
    (not functional, cannot log in) until the portal admin or a permission user
    approves it on the All Users page. A portal admin creating here is approved
    at once, as on the main Add user page."""
    db, dept = _dept_users_dept()
    if not (g.user["is_dept_admin"] or is_portal_admin(g.user)):
        abort(403)
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        full_name = (form.get("full_name") or "").strip()
        username = (form.get("username") or "").strip()
        password = (form.get("password") or "").strip()
        error = None
        if not full_name or not username:
            error = "Full name and username are required."
        elif password and password_problem(password, username):
            error = password_problem(password, username)
        elif db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            error = f"The username '{username}' is already used."
        if error:
            flash(error, "error")
        else:
            password = password or generate_password()
            approved = is_portal_admin(g.user)
            uid = db.execute("INSERT INTO users(full_name,username,password_hash,department_id,role,"
                             "must_change_password,is_dept_admin,can_ddb_attachment,approval_status,is_active,created_by) "
                             "VALUES (?,?,?,?,'user',1,0,0,?,?,?)",
                             (full_name, username, generate_password_hash(password), dept["id"],
                              "approved" if approved else "pending", 1 if approved else 0, g.user["id"])).lastrowid
            log(db, "user_add_pending" if not approved else "user_add", username)
            if not approved:
                # The portal admin and permission users get a bell notification
                # (2026-11-05): tapping it opens the Users page at this exact
                # pending account, ready to approve or reject.
                notify(db, admin_ids(db),
                       f"New account waiting for approval: {full_name} ({username}), {dept['name']}.",
                       f"/admin/users?status=pending#user-{uid}", skip=g.user["id"])
            db.commit()
            if approved:
                flash(f"User created. Temporary password for {username}: {password}", "secret")
            else:
                flash(f"User created for {dept['name']}. It is waiting for portal admin approval and cannot log in yet. Temporary password for {username}: {password}", "secret")
            return redirect(url_for("admin.dept_users"))
    return render_template("dept_user_form.html", item=form, dept=dept)
