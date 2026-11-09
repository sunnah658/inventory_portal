"""
routes_deptdb.py - the DEPARTMENT DATABASE, as tabs inside one department page.

There is no single DeptDB table any more. Under "Department database" the
department admin (or a delegate he chose) creates tabs — from a template
(Client Info, Meetings, Employee Info, Billing, Accounts) or blank — and
customises each tab's columns. Users switch tabs at the top of the page;
filter and sorting sit on top of the tabs and apply to the open tab.

Visibility / editing (per tab, per row):
- Every user in the same department can see every row in a tab.
- Only the row's owner may edit it, unless the owner shared it (with a whole
  department or one specific user, with View only or Can edit permission).
- Dept admins, their delegates and the portal admin may manage tabs and
  columns and edit every row in their department.
- Every change is written in the row's edit history, shown on the row page.

Meeting notifications live in meeting-notify tabs (the Meetings template, or
any tab with that tick): a date column that also keeps a time is a meeting
schedule, notified 7, 3 and 1 days before and on the morning of the meeting.

Used by: app.py (registers it).   Uses: core.py, auth.py, models.py, exports.py
Templates: deptdb, deptdb_form, deptdb_row, deptdb_columns, deptdb_column_edit,
deptdb_tabs, deptdb_delegates.
"""
import json
import os
import secrets
import sqlite3

import segno
from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, send_file, url_for

import config
import exports
import scanner
from auth import login_required
from core import (DDB_COLUMN_TYPES, DDB_TYPE_LABEL, col_weight, ddb_attachment_info,
                  ddb_can_delete_row, ddb_can_edit_row, ddb_can_view_row, ddb_columns,
                  ddb_create_row, ddb_display_value, ddb_history, ddb_is_tab_admin,
                  ddb_row_link, ddb_share_permission, ddb_tabs, ddb_update_row, ddb_values,
                  display_code, new_random_code_text, notify, notify_ddb_task,
                  parse_code_text, parse_form, print_col_widths, show_when)
from models import get_db, log, setting_get
from utils import csv_response, is_portal_admin, is_true_admin, like_pattern, page_info

bp = Blueprint("ddb", __name__, url_prefix="/deptdb")


def _show_mine(dept):
    """Whether the 'My rows' / 'My invoices' sub-tab is shown for this viewer
    in this department (2026-11-05): the true portal admin never gets one —
    he has no rows or invoices of his own to filter to — and a permission user
    gets one only in his own department, not in other departments. Dept
    admins and regular users only ever see their own department, so for them
    it is always shown."""
    if is_true_admin(g.user):
        return False
    if is_portal_admin(g.user) and g.user["department_id"] != dept["id"]:
        return False
    return True

# Template tabs: (key, label, starter columns)
# column: (name, type, options, required, has_time)
TEMPLATE_TABS = [
    ("client", "Client Info", [
        ("Client name", "text", None, 1, 0),
        ("Contact person", "text", None, 0, 0),
        ("Phone number", "text", None, 0, 0),
        ("Email", "text", None, 0, 0),
        ("Address", "longtext", None, 0, 0),
        ("Notes", "longtext", None, 0, 0),
    ]),
    ("meetings", "Meetings", [
        ("Client name", "text", None, 1, 0),
        ("Address", "longtext", None, 0, 0),
        ("Contact number", "text", None, 0, 0),
        ("Date", "date", None, 1, 1),
        ("Purpose", "longtext", None, 0, 0),
        ("Notes", "longtext", None, 0, 0),
    ]),
    ("employee", "Employee Info", [
        ("Employee name", "text", None, 1, 0),
        ("Employee ID", "text", None, 0, 0),
        ("Designation", "text", None, 0, 0),
        ("Phone number", "text", None, 0, 0),
        ("Email", "text", None, 0, 0),
        ("Joining date", "date", None, 0, 0),
        ("Address", "longtext", None, 0, 0),
    ]),
    ("billing", "Billing", [
        ("Client name", "text", None, 0, 0),
        ("Bill number", "text", None, 0, 0),
        ("Amount", "number", None, 0, 0),
        ("Date", "date", None, 0, 0),
        ("Status", "dropdown", "Paid\nUnpaid\nPartially paid", 0, 0),
        ("Notes", "longtext", None, 0, 0),
    ]),
    ("accounts", "Accounts", [
        ("Account / Head", "text", None, 0, 0),
        ("Type", "dropdown", "Income\nExpense", 0, 0),
        ("Amount", "number", None, 0, 0),
        ("Date", "date", None, 0, 0),
        ("Reference", "text", None, 0, 0),
        ("Notes", "longtext", None, 0, 0),
    ]),
    ("custom", "Custom tab (blank)", []),
]
TEMPLATE_MAP = {k: (label, cols) for k, label, cols in TEMPLATE_TABS}


# ---------------------------------------------------------------- which department, which tab
def _dept():
    """(db, department row, is_tab_admin). A normal user always uses his own
    department; the portal admin may pick any with ?dept=."""
    db = get_db()
    dept_id = g.user["department_id"]
    if is_portal_admin(g.user):
        dept_id = request.values.get("dept", type=int) or dept_id
    dept = db.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone() if dept_id else None
    if dept is None:
        flash("You are not in a department yet. Ask the admin.", "error")
        abort(403)
    return db, dept, ddb_is_tab_admin(db, g.user, dept["id"])


def _tab_admin():
    db, dept, is_admin = _dept()
    if not is_admin:
        abort(403)
    return db, dept


def _get_tab(db, dept, tab_id=None):
    tabs = ddb_tabs(db, dept["id"])
    if not tabs:
        return None, tabs
    if tab_id is not None:
        for tb in tabs:
            if tb["id"] == tab_id:
                return tb, tabs
        abort(404)
    return tabs[0], tabs


def _back(dept, tab=None):
    out = {}
    if is_portal_admin(g.user):
        out["dept"] = dept["id"]
    if tab is not None:
        out["tab"] = tab["id"]
    return out


def _row(rid):
    db = get_db()
    row = db.execute("SELECT r.*, u.full_name AS owner_name, u.is_active AS owner_is_active, u.is_deleted AS owner_is_deleted, d.name AS department_name FROM ddb_rows r "
                     "JOIN users u ON u.id=r.owner_id JOIN departments d ON d.id=r.department_id "
                     "WHERE r.id=?", (rid,)).fetchone()
    if row is None:
        abort(404)
    if not ddb_can_view_row(db, g.user, row):
        abort(404)
    if row["deleted_at"] and not ddb_is_tab_admin(db, g.user, row["department_id"]):
        abort(404)
    return db, row


def _can_create_attachment(user, dept_id=None):
    """Portal admin always; a dept admin only if the portal admin gave them
    access. A delegate inherits it when a dept admin of his department has it."""
    db = get_db()
    if is_portal_admin(user):
        return True
    try:
        if user["is_dept_admin"] and user["can_ddb_attachment"]:
            return True
    except Exception:
        return False
    dept_id = dept_id or user["department_id"]
    if dept_id and ddb_is_tab_admin(db, user, dept_id):
        return db.execute("SELECT 1 FROM users WHERE department_id=? AND is_dept_admin=1 AND can_ddb_attachment=1",
                          (dept_id,)).fetchone() is not None
    return False


def _ddb_file_path(stored):
    return os.path.join(config.UPLOAD_DIR, "ddb_attachments", stored)


def _save_ddb_file(file_storage, dept):
    if not file_storage or not file_storage.filename:
        return None, None
    original = file_storage.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200]
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in config.ALLOWED_EXTENSIONS:
        return None, f"File type '.{ext}' is not allowed for attachments."
    if scanner.enabled():
        verdict, detail = scanner.scan_stream(file_storage.stream)
        try:
            file_storage.stream.seek(0)
        except Exception:
            pass
        if verdict != "clean":
            return None, f"'{original}' could not be scanned, so it was not uploaded. Tell the admin ({detail})."
    folder = os.path.join(config.UPLOAD_DIR, "ddb_attachments")
    os.makedirs(folder, exist_ok=True)
    stored = secrets.token_hex(10) + "." + ext
    file_storage.save(os.path.join(folder, stored))
    limit = min(int(dept["attachment_max_mb"] or 10), config.MAX_UPLOAD_MB) * 1024 * 1024
    if os.path.getsize(os.path.join(folder, stored)) > limit:
        os.remove(os.path.join(folder, stored))
        return None, f"'{original}' is too large (max {limit // 1024 // 1024} MB)."
    return json.dumps({"stored": stored, "original": original}), None


def _handle_ddb_files(dept, cols, values, existing):
    errors, saved, to_delete = [], [], []
    for c in cols:
        if c["col_type"] != "attachment":
            continue
        cid = c["id"]
        if request.form.get(f"remove_c{cid}"):
            old = ddb_attachment_info(existing.get(cid))
            if old:
                to_delete.append(old["stored"])
            values[cid] = None
            continue
        file_storage = request.files.get(f"c{cid}_file")
        if file_storage and file_storage.filename:
            val, err = _save_ddb_file(file_storage, dept)
            if err:
                errors.append(err)
            else:
                old = ddb_attachment_info(existing.get(cid))
                if old:
                    to_delete.append(old["stored"])
                info = ddb_attachment_info(val)
                if info:
                    saved.append(info["stored"])
                values[cid] = val
        else:
            values[cid] = existing.get(cid)
        if c["required"] and not values[cid]:
            errors.append(f"{c['name']} is required.")
    return errors, saved, to_delete


def _delete_ddb_files(stored_list):
    for s in stored_list:
        try:
            os.remove(_ddb_file_path(s))
        except OSError:
            pass


def _display_map(db, rows, cols):
    raw = ddb_values(db, [r["id"] for r in rows])
    vmap, urls = {}, {}
    for r in rows:
        vmap[r["id"]] = {}
        urls[r["id"]] = {}
        for c in cols:
            v = raw[r["id"]].get(c["id"])
            if c["col_type"] == "attachment":
                info = ddb_attachment_info(v)
                vmap[r["id"]][c["id"]] = info["original"] if info else ""
                if info:
                    urls[r["id"]][c["id"]] = url_for("ddb.download_attachment", rid=r["id"], cid=c["id"])
            else:
                vmap[r["id"]][c["id"]] = v
    return vmap, urls


# ---------------------------------------------------------------- list, search, filter, sort (on top of the tabs)
def _filters(db, dept, tab, is_admin, args):
    where, params = ["r.department_id=?", "r.tab_id=?"], [dept["id"], tab["id"]]
    deleted = bool(args.get("deleted")) and is_admin
    where.append("r.deleted_at IS NOT NULL" if deleted else "r.deleted_at IS NULL")
    mine = bool(args.get("mine"))
    if mine:
        where.append("r.owner_id=?")
        params.append(g.user["id"])
    q = (args.get("q") or "").strip()
    if q:
        where.append("EXISTS (SELECT 1 FROM ddb_values v WHERE v.row_id=r.id AND v.value LIKE ? ESCAPE '\\')")
        params.append(like_pattern(q))
    fcol, fval = (args.get("fcol") or "").strip(), (args.get("fval") or "").strip()
    if fcol and fval:
        where.append("EXISTS (SELECT 1 FROM ddb_values v JOIN ddb_columns c ON c.id=v.column_id "
                     "AND c.removed_at IS NULL WHERE v.row_id=r.id AND c.tab_id=? "
                     "AND lower(c.name)=lower(?) AND v.value LIKE ? ESCAPE '\\')")
        params += [tab["id"], fcol, like_pattern(fval)]
    sort = args.get("sort", "updated")
    direction = "asc" if args.get("dir") == "asc" else "desc"
    d = "ASC" if direction == "asc" else "DESC"
    order, op = f"r.updated_at {d}, r.id {d}", []
    if sort == "created":
        order = f"r.created_at {d}, r.id {d}"
    elif sort.startswith("col:"):
        name = sort[4:]
        numeric = db.execute("SELECT 1 FROM ddb_columns WHERE tab_id=? AND lower(name)=lower(?) "
                             "AND col_type='number' AND removed_at IS NULL", (tab["id"], name)).fetchone()
        sub = ("(SELECT v.value FROM ddb_values v JOIN ddb_columns c ON c.id=v.column_id AND c.removed_at IS NULL "
               "WHERE v.row_id=r.id AND c.tab_id=? AND lower(c.name)=lower(?) LIMIT 1)")
        expr = f"CAST({sub} AS REAL)" if numeric else f"{sub} COLLATE NOCASE"
        order = f"({sub} IS NULL), {expr} {d}, r.id DESC"
        op = [tab["id"], name, tab["id"], name]
    else:
        sort = "updated"
    info = {"sort": sort, "dir": direction, "fcol": fcol, "fval": fval}
    return " AND ".join(where), params, order, op, info, q, mine, deleted


@bp.route("")
@login_required
def index():
    db, dept, is_admin = _dept()
    _wanted = parse_code_text(request.args.get("q"))
    # The Invoices and Request items tabs have their own share-code search
    # (filtered to that department's invoices / requests). A code typed in
    # any other tab's search box goes to the Search QR page, which looks
    # all over for the code — a record, an invoice, a request or a row.
    if _wanted is not None and request.args.get("tab") not in ("invoices", "requests"):
        return redirect(url_for("public.search_qr", q=_wanted))
    if request.args.get("tab") == "invoices":
        return _invoice_tab_view(db, dept, is_admin, request.args)
    if request.args.get("tab") == "requests":
        return _request_tab_view(db, dept, is_admin, request.args)
    show_mine = _show_mine(dept)
    args = request.args.copy()
    if not show_mine:
        args.pop("mine", None)   # a bookmarked mine=1 just shows All
    tab, tabs = _get_tab(db, dept, args.get("tab", type=int))
    if tab is None:
        return render_template("deptdb.html", dept=dept, tab=None, tabs=[], level="manager" if is_admin else "own",
                               cols=[], rows=[], vmap={}, attach_urls={}, info={"sort": "updated", "dir": "desc", "fcol": "", "fval": ""},
                               q="", mine=False, deleted=False, total=0, page=1, pages=1,
                               counts={"all": 0, "mine": 0, "deleted": 0}, keep={}, can_add=False, names=[],
                               show_mine=show_mine, widths=[],
                               depts=db.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
                               if is_portal_admin(g.user) else [],
                               is_admin=is_admin, can_edit_row=lambda r: False, can_delete_row=lambda r: False)
    where, params, order, op, info, q, mine, deleted = _filters(db, dept, tab, is_admin, args)
    total = db.execute("SELECT COUNT(*) FROM ddb_rows r WHERE " + where, params).fetchone()[0]
    page, pages, offset = page_info(total, request.args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute("SELECT r.*, u.full_name AS owner_name, u.is_active AS owner_is_active, u.is_deleted AS owner_is_deleted FROM ddb_rows r JOIN users u ON u.id=r.owner_id "
                      "WHERE " + where + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                      params + op + [config.PER_PAGE, offset]).fetchall()
    cols = ddb_columns(db, dept["id"], tab_id=tab["id"])
    # Print widths for this tab's columns plus the trailing Added by column.
    widths = print_col_widths([col_weight(c["col_type"]) for c in cols] + [1.0])
    counts = {
        "all": db.execute("SELECT COUNT(*) FROM ddb_rows WHERE department_id=? AND tab_id=? AND deleted_at IS NULL",
                          (dept["id"], tab["id"])).fetchone()[0],
        "mine": db.execute("SELECT COUNT(*) FROM ddb_rows WHERE department_id=? AND tab_id=? AND deleted_at IS NULL "
                           "AND owner_id=?", (dept["id"], tab["id"], g.user["id"])).fetchone()[0],
        "deleted": db.execute("SELECT COUNT(*) FROM ddb_rows WHERE department_id=? AND tab_id=? AND deleted_at IS NOT NULL",
                              (dept["id"], tab["id"])).fetchone()[0] if is_admin else 0}
    keep = {k: v for k, v in args.items() if k not in ("page",)}
    if is_portal_admin(g.user):
        keep["dept"] = dept["id"]
    _vmap, _urls = _display_map(db, rows, cols)
    can_add_here = bool(cols) and (is_portal_admin(g.user) or g.user["department_id"] == dept["id"])
    return render_template(
        "deptdb.html", dept=dept, tab=tab, tabs=tabs, level="manager" if is_admin else "own", cols=cols, rows=rows,
        vmap=_vmap, attach_urls=_urls, info=info, q=q, mine=mine, deleted=deleted,
        total=total, page=page, pages=pages, counts=counts, keep=keep, show_mine=show_mine,
        widths=widths,
        can_add=can_add_here, names=[c["name"] for c in cols], is_admin=is_admin,
        depts=db.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        if is_portal_admin(g.user) else [],
        can_edit_row=lambda r: ddb_can_edit_row(db, g.user, r) and not r["deleted_at"],
        can_delete_row=lambda r: ddb_can_delete_row(db, g.user, r) and not r["deleted_at"])


@bp.route("/export")
@login_required
def export():
    db, dept, is_admin = _dept()
    tab, _tabs = _get_tab(db, dept, request.args.get("tab", type=int))
    if tab is None:
        flash("This department database has no tabs yet.", "error")
        return redirect(url_for("ddb.index", **_back(dept)))
    where, params, order, op, _info, _q, _mine, _deleted = _filters(db, dept, tab, is_admin, request.args)
    rows = db.execute("SELECT r.*, u.full_name AS owner_name FROM ddb_rows r JOIN users u ON u.id=r.owner_id "
                      "WHERE " + where + " ORDER BY " + order, params + op).fetchall()
    # A selection (ids=1,2,3) exports only those rows; without it, everything
    # the current filters match is exported, as before.
    ids = request.args.get("ids")
    if ids:
        idset = {x for x in ids.split(",") if x.isdigit()}
        rows = [r for r in rows if str(r["id"]) in idset]
    cols = ddb_columns(db, dept["id"], tab_id=tab["id"])
    vals = ddb_values(db, [r["id"] for r in rows])
    header = [c["name"] for c in cols] + ["Added by", "Last updated"]
    out = [[(ddb_display_value(c, vals[r["id"]].get(c["id"])) if c["col_type"] == "attachment"
             else (show_when(vals[r["id"]].get(c["id"])) if c["col_type"] == "date" else vals[r["id"]].get(c["id"])))
            for c in cols] + [r["owner_name"], r["updated_at"]] for r in rows]
    kinds = ["number" if c["col_type"] == "number" else "text" for c in cols] + ["text", "text"]
    fmt = request.args.get("fmt", "xlsx")
    log(db, "export", f"department database {dept['name']} / {tab['name']}: {fmt}, {len(rows)} rows")
    db.commit()
    if fmt == "csv":
        return csv_response(header, out, "department_database_" + dept["name"] + "_" + tab["name"])
    return exports.table_file("pdf" if fmt == "pdf" else "xlsx", f"{dept['name']} database — {tab['name']}", header, out, kinds,
                              f"{len(rows)} rows", setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME),
                              "department_database_" + dept["name"] + "_" + tab["name"])



# ---------------------------------------------------------------- Invoices tab (default tab inside Department Database)
def _invoice_tab_view(db, dept, is_admin, args):
    """The invoice page, as a default tab inside Department Database. Every
    feature of invoices is unchanged — only where the list lives moved.
    Sub-tabs: All, My invoices (only the current user's invoices), plus one
    per invoice type in this department. A new type (template) created by
    the dept admin automatically gets its own sub-tab, because the sub-tabs
    are built from the department's templates and the templates that already
    have invoices. Everyone in the department can see every invoice in the
    tab; editing rules are unchanged (owner edits a draft, dept admin marks
    Paid/Void). Templates stay outside, on the dept-admin Invoice templates
    page."""
    from routes_invoices import _shared_dept_ids
    scope = [dept["id"]]
    if is_admin and not is_portal_admin(g.user) and g.user["department_id"] == dept["id"]:
        scope += [d for d in _shared_dept_ids(db, g.user) if d not in scope]
    # sub-tabs: active templates of this department, plus templates that already have invoices in scope
    sub = {}
    for row in db.execute("SELECT id, name FROM invoice_templates WHERE department_id=? AND status='active' ORDER BY id",
                          (dept["id"],)).fetchall():
        sub[row["id"]] = row["name"]
    qmarks = ",".join("?" * len(scope))
    for row in db.execute(f"SELECT DISTINCT t.id, t.name FROM invoice_templates t JOIN invoices i ON i.template_id=t.id "
                          f"WHERE i.department_id IN ({qmarks}) ORDER BY t.id", scope).fetchall():
        sub[row["id"]] = row["name"]
    invtype = args.get("invtype") or "all"
    try:
        invtype_id = int(invtype) if invtype != "all" else None
    except ValueError:
        invtype_id = None
    if invtype_id is not None and invtype_id not in sub:
        invtype, invtype_id = "all", None
    # counts per sub-tab (scope only, before user/status filters)
    counts = {"all": db.execute(f"SELECT COUNT(*) FROM invoices WHERE department_id IN ({qmarks})", scope).fetchone()[0]}
    counts["mine"] = db.execute(f"SELECT COUNT(*) FROM invoices WHERE department_id IN ({qmarks}) AND owner_id=?",
                                scope + [g.user["id"]]).fetchone()[0]
    for tid in sub:
        counts[tid] = db.execute("SELECT COUNT(*) FROM invoices WHERE department_id IN (%s) AND template_id=?" % qmarks,
                                 scope + [tid]).fetchone()[0]
    for st in ("issued", "paid", "draft", "void"):
        counts[st] = db.execute(f"SELECT COUNT(*) FROM invoices WHERE department_id IN ({qmarks}) AND status=?",
                                scope + [st]).fetchone()[0]
    # filters: user, status, search, sort — on top of the tab
    show_mine = _show_mine(dept)
    user_filter = args.get("user") or ""
    if not show_mine and user_filter == "mine":
        user_filter = ""   # a bookmarked user=mine just shows All
    status = args.get("status") or ""
    q = (args.get("q") or "").strip()
    sort = args.get("sort") or "newest"
    where = [f"i.department_id IN ({qmarks})"]
    params = list(scope)
    if invtype_id is not None:
        where.append("i.template_id=?"); params.append(invtype_id)
    if user_filter == "mine":
        where.append("i.owner_id=?"); params.append(g.user["id"])
    elif user_filter.isdigit():
        where.append("i.owner_id=?"); params.append(int(user_filter))
    if status in ("draft", "issued", "paid", "void"):
        where.append("i.status=?"); params.append(status)
    if q:
        where.append("(i.customer_name LIKE ? ESCAPE '\\' OR i.number LIKE ? ESCAPE '\\' OR i.public_code LIKE ? ESCAPE '\\')")
        params += [like_pattern(q)] * 3
    order = {"newest": "i.id DESC", "oldest": "i.id ASC", "amount_desc": "i.total DESC, i.id DESC",
             "amount_asc": "i.total ASC, i.id ASC", "date_desc": "i.invoice_date DESC, i.id DESC"}.get(sort, "i.id DESC")
    if sort not in ("newest", "oldest", "amount_desc", "amount_asc", "date_desc"):
        sort = "newest"
    sql_where = " WHERE " + " AND ".join(where)
    total = db.execute("SELECT COUNT(*) FROM invoices i" + sql_where, params).fetchone()[0]
    page, pages, offset = page_info(total, args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute("SELECT i.*, t.name AS template_name, u.full_name AS owner_name, d.name AS dept_name "
                      "FROM invoices i LEFT JOIN invoice_templates t ON t.id=i.template_id "
                      "LEFT JOIN users u ON u.id=i.owner_id LEFT JOIN departments d ON d.id=i.department_id "
                      + sql_where + f" ORDER BY {order} LIMIT ? OFFSET ?", params + [config.PER_PAGE, offset]).fetchall()
    keep = {k: v for k, v in args.items() if k not in ("page",) and not (k == "user" and v == "mine" and not show_mine)}
    if is_portal_admin(g.user):
        keep["dept"] = dept["id"]
    keep["tab"] = "invoices"
    users = db.execute("SELECT id, full_name FROM users WHERE department_id=? AND is_active=1 ORDER BY full_name",
                       (dept["id"],)).fetchall()
    create_templates = db.execute("SELECT * FROM invoice_templates WHERE department_id=? AND status='active' ORDER BY id",
                                  (dept["id"],)).fetchall()
    return render_template("deptdb_invoices.html", dept=dept, tabs=ddb_tabs(db, dept["id"]), is_admin=is_admin,
                           sub_tabs=[{"id": tid, "name": name} for tid, name in sub.items()],
                           invtype=invtype, invtype_id=invtype_id, counts=counts, rows=rows,
                           users=users, user_filter=user_filter, status=status, q=q, sort=sort,
                           total=total, page=page, pages=pages, keep=keep, create_templates=create_templates,
                           show_mine=show_mine,
                           depts=db.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
                           if is_portal_admin(g.user) else [],
                           can_edit_invoice=lambda r: r["owner_id"] == g.user["id"] and r["status"] == "draft")


# ---------------------------------------------------------------- Request items tab (default tab inside Department Database)
def _request_tab_view(db, dept, is_admin, args):
    """The Request items page, as a default tab inside Department Database
    (like Invoices). Sub-tabs: My request (only the current user's
    requests), All request, Other's request (only for HR & Admin users —
    only they can receive a request, so only they ever see one sent TO
    them). In All request, the portal admin, administrative
    permission users and HR & Admin users see ALL departments' requests;
    users of other departments see only their own department's requests.
    The filter is BOTH department and status, with a search bar (search
    by name or Department). A request is sent to one specific HR & Admin
    user; the recipient can print it, download its PDF and change its
    status (Pending / Issued / Paid / Handovered)."""
    from routes_requests import STATUSES, can_see_all_departments, hr_admin_dept_id
    can_all = can_see_all_departments(db, g.user)
    show_mine = _show_mine(dept)
    # Other's request is only for HR & Admin users: only they can receive a
    # request, so for everyone else the sub-tab would always be empty.
    show_others = bool(show_mine) and g.user["department_id"] == hr_admin_dept_id(db)
    reqtab = args.get("reqtab") or "all"
    if reqtab not in ("my", "all", "others"):
        reqtab = "all"
    if not show_mine and reqtab in ("my", "others"):
        reqtab = "all"   # a bookmarked my/others just shows All
    if not show_others and reqtab == "others":
        reqtab = "all"   # a bookmarked others just shows All
    # Departments this viewer may see in All request.
    if can_all:
        all_depts = [r["id"] for r in db.execute("SELECT id FROM departments ORDER BY id").fetchall()]
    else:
        all_depts = [g.user["department_id"]]
    fdept = args.get("fdept", type=int)
    if fdept and can_all and fdept in all_depts:
        scope = [fdept]
    elif fdept and not can_all:
        scope = [g.user["department_id"]]
    else:
        scope = list(all_depts)
    qmarks = ",".join("?" * len(scope))
    # counts per sub-tab (scope only, before status/search filters)
    counts = {}
    counts["all"] = db.execute(f"SELECT COUNT(*) FROM item_requests WHERE department_id IN ({qmarks})", scope).fetchone()[0]
    counts["mine"] = db.execute(f"SELECT COUNT(*) FROM item_requests WHERE department_id IN ({qmarks}) AND owner_id=?",
                                scope + [g.user["id"]]).fetchone()[0]
    counts["others"] = db.execute(f"SELECT COUNT(*) FROM item_requests WHERE department_id IN ({qmarks}) AND recipient_id=?",
                                  scope + [g.user["id"]]).fetchone()[0]
    for st in STATUSES:
        counts[st] = db.execute(f"SELECT COUNT(*) FROM item_requests WHERE department_id IN ({qmarks}) AND status=?",
                                scope + [st]).fetchone()[0]
    # filters: status, department, search, sort — on top of the sub-tab
    status = args.get("status") or ""
    q = (args.get("q") or "").strip()
    sort = args.get("sort") or "newest"
    where = [f"r.department_id IN ({qmarks})"]
    params = list(scope)
    if reqtab == "my":
        where.append("r.owner_id=?"); params.append(g.user["id"])
    elif reqtab == "others":
        where.append("r.recipient_id=?"); params.append(g.user["id"])
    if status in STATUSES:
        where.append("r.status=?"); params.append(status)
    if q:
        like = like_pattern(q)
        where.append("(u.full_name LIKE ? ESCAPE '\\' OR ru.full_name LIKE ? ESCAPE '\\' OR k.name LIKE ? ESCAPE '\\' "
                     "OR r.number LIKE ? ESCAPE '\\' OR r.public_code LIKE ? ESCAPE '\\' OR d.name LIKE ? ESCAPE '\\')")
        params += [like] * 6
    order = {"newest": "r.id DESC", "oldest": "r.id ASC", "amount_desc": "r.total DESC, r.id DESC",
             "amount_asc": "r.total ASC, r.id ASC", "date_desc": "r.request_date DESC, r.id DESC"}.get(sort, "r.id DESC")
    if sort not in ("newest", "oldest", "amount_desc", "amount_asc", "date_desc"):
        sort = "newest"
    sql_where = " WHERE " + " AND ".join(where)
    total = db.execute("SELECT COUNT(*) FROM item_requests r LEFT JOIN users u ON u.id=r.owner_id "
                       "LEFT JOIN users ru ON ru.id=r.recipient_id LEFT JOIN item_request_kinds k ON k.id=r.kind_id "
                       "LEFT JOIN departments d ON d.id=r.department_id" + sql_where, params).fetchone()[0]
    page, pages, offset = page_info(total, args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute("SELECT r.*, k.name AS kind_name, u.full_name AS owner_name, ru.full_name AS recipient_name, d.name AS dept_name "
                      "FROM item_requests r LEFT JOIN item_request_kinds k ON k.id=r.kind_id "
                      "LEFT JOIN users u ON u.id=r.owner_id LEFT JOIN users ru ON ru.id=r.recipient_id "
                      "LEFT JOIN departments d ON d.id=r.department_id"
                      + sql_where + f" ORDER BY {order} LIMIT ? OFFSET ?", params + [config.PER_PAGE, offset]).fetchall()
    keep = {k: v for k, v in args.items() if k not in ("page",) and not (k == "reqtab" and ((v == "my" and not show_mine) or (v == "others" and not show_others)))}
    if is_portal_admin(g.user):
        keep["dept"] = dept["id"]
    keep["tab"] = "requests"
    create_kinds = db.execute("SELECT * FROM item_request_kinds WHERE department_id=? AND status='active' ORDER BY id",
                              (dept["id"],)).fetchall()
    return render_template("deptdb_requests.html", dept=dept, tabs=ddb_tabs(db, dept["id"]), is_admin=is_admin,
                           reqtab=reqtab, counts=counts, rows=rows,
                           status=status, q=q, sort=sort, fdept=fdept or "",
                           total=total, page=page, pages=pages, keep=keep, create_kinds=create_kinds,
                           show_mine=show_mine, show_others=show_others, can_all=can_all,
                           depts=db.execute("SELECT id, name FROM departments ORDER BY name").fetchall() if can_all else [],
                           can_status=lambda r: r["recipient_id"] == g.user["id"])


# ---------------------------------------------------------------- tabs (admins / delegates)
@bp.route("/tabs", methods=["GET", "POST"])
@login_required
def tabs():
    db, dept = _tab_admin()
    if request.method == "POST":
        name = " ".join((request.form.get("name") or "").split())[:60]
        if name.lower() == "general":
            # The General tab was deleted for all users (2026-11-05); it must
            # not be created again under that name.
            flash("The General tab was removed for all users and cannot be created again.", "error")
            return redirect(url_for("ddb.tabs", **_back(dept)))
        template = request.form.get("template", "custom")
        if template not in TEMPLATE_MAP:
            template = "custom"
        meeting = 1 if (template == "meetings" or request.form.get("meeting_notify")) else 0
        if not name:
            flash("Type the tab name.", "error")
        else:
            pos = db.execute("SELECT COALESCE(MAX(position),-1)+1 FROM ddb_tabs WHERE department_id=?",
                             (dept["id"],)).fetchone()[0]
            try:
                tab_id = db.execute("INSERT INTO ddb_tabs(department_id,name,template,meeting_notify,position,created_by) "
                                    "VALUES (?,?,?,?,?,?)",
                                    (dept["id"], name, template, meeting, pos, g.user["id"])).lastrowid
                _label, starter = TEMPLATE_MAP[template]
                for i, (cname, ctype, opts, req, has_time) in enumerate(starter):
                    db.execute("INSERT INTO ddb_columns(department_id,tab_id,name,col_type,options,required,has_time,position) "
                               "VALUES (?,?,?,?,?,?,?,?)",
                               (dept["id"], tab_id, cname, ctype, opts, req, has_time, i))
                log(db, "ddb_tab_add", f"{dept['name']}: {name} ({template})")
                notify_ddb_task(db, g.user, dept,
                                f"{g.user['full_name']} created the tab '{name}' in {dept['name']}.",
                                url_for("ddb.index", dept=dept["id"], tab=tab_id))
                db.commit()
                flash(f"Tab '{name}' created.", "ok")
            except sqlite3.IntegrityError:
                db.rollback()
                flash(f"A tab named '{name}' already exists.", "error")
        return redirect(url_for("ddb.tabs", **_back(dept)))
    all_tabs = db.execute("SELECT t.*, (SELECT COUNT(*) FROM ddb_rows r WHERE r.tab_id=t.id AND r.deleted_at IS NULL) AS rows "
                          "FROM ddb_tabs t WHERE t.department_id=? AND NOT (t.removed_at IS NOT NULL AND LOWER(t.name)='general') ORDER BY t.removed_at IS NOT NULL, t.position, t.id",
                          (dept["id"],)).fetchall()
    return render_template("deptdb_tabs.html", dept=dept, tabs=all_tabs, templates=TEMPLATE_TABS)


@bp.route("/tabs/<int:tab_id>/edit", methods=["POST"])
@login_required
def tab_edit(tab_id):
    db, dept = _tab_admin()
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=? AND department_id=?", (tab_id, dept["id"])).fetchone()
    if tab is None:
        abort(404)
    name = " ".join((request.form.get("name") or "").split())[:60]
    meeting = 1 if request.form.get("meeting_notify") else 0
    if name.lower() == "general":
        flash("The General tab was removed for all users and cannot be used as a name.", "error")
        return redirect(url_for("ddb.tabs", **_back(dept)))
    if not name:
        flash("Type the tab name.", "error")
    else:
        try:
            db.execute("UPDATE ddb_tabs SET name=?, meeting_notify=? WHERE id=?", (name, meeting, tab_id))
            log(db, "ddb_tab_edit", f"{dept['name']}: {name}")
            notify_ddb_task(db, g.user, dept,
                            f"{g.user['full_name']} renamed the tab '{tab['name']}' to '{name}' in {dept['name']}.",
                            url_for("ddb.index", dept=dept["id"]))
            db.commit()
            flash("Tab saved.", "ok")
        except sqlite3.IntegrityError:
            db.rollback()
            flash(f"A tab named '{name}' already exists.", "error")
    return redirect(url_for("ddb.tabs", **_back(dept)))


@bp.route("/tabs/<int:tab_id>/delete", methods=["POST"])
@login_required
def tab_delete(tab_id):
    db, dept = _tab_admin()
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=? AND department_id=?", (tab_id, dept["id"])).fetchone()
    if tab is None:
        abort(404)
    db.execute("UPDATE ddb_tabs SET removed_at=datetime('now','localtime') WHERE id=?", (tab_id,))
    log(db, "ddb_tab_delete", f"{dept['name']}: {tab['name']}")
    notify_ddb_task(db, g.user, dept,
                    f"{g.user['full_name']} deleted the tab '{tab['name']}' in {dept['name']}.",
                    url_for("ddb.index", dept=dept["id"]))
    db.commit()
    flash(f"Tab '{tab['name']}' deleted. Its rows are hidden until the tab is restored.", "ok")
    return redirect(url_for("ddb.tabs", **_back(dept)))


@bp.route("/tabs/<int:tab_id>/restore", methods=["POST"])
@login_required
def tab_restore(tab_id):
    db, dept = _tab_admin()
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=? AND department_id=?", (tab_id, dept["id"])).fetchone()
    if tab is None:
        abort(404)
    if tab["name"].lower() == "general":
        # The General tab was deleted for all users (2026-11-05); restoring it
        # would put it back in front of every user, so it stays deleted. Its
        # rows are still in the database.
        flash("The General tab was removed for all users and cannot be restored.", "error")
        return redirect(url_for("ddb.tabs", **_back(dept)))
    try:
        db.execute("UPDATE ddb_tabs SET removed_at=NULL WHERE id=?", (tab_id,))
        log(db, "ddb_tab_restore", f"{dept['name']}: {tab['name']}")
        notify_ddb_task(db, g.user, dept,
                        f"{g.user['full_name']} restored the tab '{tab['name']}' in {dept['name']}.",
                        url_for("ddb.index", dept=dept["id"], tab=tab_id))
        db.commit()
        flash("Tab restored.", "ok")
    except sqlite3.IntegrityError:
        db.rollback()
        flash(f"A tab named '{tab['name']}' exists already. Rename it first, then restore.", "error")
    return redirect(url_for("ddb.tabs", **_back(dept)))


# ---------------------------------------------------------------- delegates (admins / delegates)
@bp.route("/delegates", methods=["GET", "POST"])
@login_required
def delegates():
    db, dept = _tab_admin()
    if request.method == "POST":
        uid = request.form.get("user_id", type=int)
        member = db.execute("SELECT * FROM users WHERE id=? AND department_id=? AND is_active=1",
                            (uid, dept["id"])).fetchone() if uid else None
        if member is None:
            flash("Choose a user from this department.", "error")
        else:
            db.execute("INSERT OR IGNORE INTO ddb_delegates(department_id,user_id,granted_by) VALUES (?,?,?)",
                       (dept["id"], uid, g.user["id"]))
            notify(db, [uid], f"You can now do everything a department admin can do in the {dept['name']} department database.",
                   "/deptdb", skip=g.user["id"])
            notify_ddb_task(db, g.user, dept,
                            f"{g.user['full_name']} made {member['full_name']} a delegate in {dept['name']}.",
                            url_for("ddb.delegates", dept=dept["id"]))
            log(db, "ddb_delegate", f"{dept['name']}: {member['username']} made a department-database delegate")
            db.commit()
            flash(f"{member['full_name']} can now do everything a department admin can do in this department database.", "ok")
        return redirect(url_for("ddb.delegates", **_back(dept)))
    members = db.execute("SELECT u.id, u.full_name, u.username, u.is_dept_admin, u.role, "
                         "CASE WHEN d.user_id IS NOT NULL THEN 1 ELSE 0 END AS is_delegate FROM users u "
                         "LEFT JOIN ddb_delegates d ON d.user_id=u.id AND d.department_id=? "
                         "WHERE u.department_id=? AND u.is_active=1 ORDER BY u.full_name",
                         (dept["id"], dept["id"])).fetchall()
    return render_template("deptdb_delegates.html", dept=dept, members=members)


@bp.route("/delegates/<int:uid>/revoke", methods=["POST"])
@login_required
def delegate_revoke(uid):
    db, dept = _tab_admin()
    member = db.execute("SELECT full_name, username FROM users WHERE id=?", (uid,)).fetchone()
    db.execute("DELETE FROM ddb_delegates WHERE department_id=? AND user_id=?", (dept["id"], uid))
    notify_ddb_task(db, g.user, dept,
                    f"{g.user['full_name']} removed {member['full_name'] if member else 'a user'} as a delegate in {dept['name']}.",
                    url_for("ddb.delegates", dept=dept["id"]))
    log(db, "ddb_delegate_revoke", f"{dept['name']}: user {uid} no longer a department-database delegate")
    db.commit()
    flash("Delegate removed.", "ok")
    return redirect(url_for("ddb.delegates", **_back(dept)))


# ---------------------------------------------------------------- one row
@bp.route("/row/<int:rid>")
@login_required
def row_detail(rid):
    db, row = _row(rid)
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (row["tab_id"],)).fetchone() if row["tab_id"] else None
    cols = ddb_columns(db, row["department_id"], tab_id=row["tab_id"]) if row["tab_id"] else []
    _vmap, _urls = _display_map(db, [row], cols)
    is_admin = ddb_is_tab_admin(db, g.user, row["department_id"])
    can_share = (row["owner_id"] == g.user["id"] or is_admin) and not row["deleted_at"]
    shares = db.execute("SELECT s.*, d.name AS dept_name, u.full_name AS user_name FROM ddb_row_shares s "
                        "LEFT JOIN departments d ON d.id=s.department_id LEFT JOIN users u ON u.id=s.user_id "
                        "WHERE s.row_id=? ORDER BY s.id", (rid,)).fetchall()
    return render_template(
        "deptdb_row.html", row=row, tab=tab, cols=cols, vals=_vmap[rid], attach_urls=_urls[rid],
        history=db.execute("SELECT * FROM ddb_history WHERE row_id=? ORDER BY id DESC LIMIT 100", (rid,)).fetchall(),
        can_edit=ddb_can_edit_row(db, g.user, row) and not row["deleted_at"],
        can_delete=ddb_can_delete_row(db, g.user, row) and not row["deleted_at"],
        can_restore=is_admin and bool(row["deleted_at"]),
        can_share=can_share, shares=shares, is_admin=is_admin,
        departments=db.execute("SELECT id, name FROM departments ORDER BY name").fetchall() if can_share else [],
        users=db.execute("SELECT u.id, u.full_name, d.name AS dept_name FROM users u LEFT JOIN departments d "
                         "ON d.id=u.department_id WHERE u.is_active=1 ORDER BY d.name, u.full_name").fetchall() if can_share else [],
        can_manage_public=_can_manage_row_public(db, g.user, row),
        qr_svg=_qr_svg(url_for("ddb.row_code_page", code=row["public_code"], _external=True)) if row["public_code"] else None)


def _qr_svg(url):
    return segno.make(url, error="m").svg_inline(scale=4, border=1, dark="#10283a", omitsize=True)


def _new_ddb_code(db):
    """A random HRC-##### code unique across records, invoices, requests and rows."""
    return new_random_code_text(db)


def _can_manage_row_public(db, user, row):
    """The row's owner, or a tab admin (portal admin, dept admin or delegate)."""
    return row["owner_id"] == user["id"] or ddb_is_tab_admin(db, user, row["department_id"])


# ---------------------------------------------------------------- a row's public QR
@bp.route("/row/<int:rid>/public", methods=["POST"])
@login_required
def row_public(rid):
    """Turn a Department Database row's public QR on or off, or make a new
    scan link (which kills the old printed QR's code). Every tab's rows can
    get a public QR, not only invoices and requests."""
    db, row = _row(rid)
    if row["deleted_at"] or not _can_manage_row_public(db, g.user, row):
        abort(403)
    action = request.form.get("action", "save")
    if action == "save":
        code = row["public_code"] or _new_ddb_code(db)
        db.execute("UPDATE ddb_rows SET public_code=?, public_enabled=1 WHERE id=?", (code, rid))
        db.commit()
        log(db, "public_qr_on", f"ddb row {rid} {code}")
        db.commit()
        flash(f"The public QR is on. Its code is {code}. Anyone logged in can search it in Search QR.", "ok")
    elif action == "off":
        db.execute("UPDATE ddb_rows SET public_enabled=0 WHERE id=?", (rid,))
        db.commit()
        log(db, "public_qr_off", f"ddb row {rid}")
        db.commit()
        flash("The public QR is off. Scanning it shows nothing.", "ok")
    elif action == "regenerate":
        code = _new_ddb_code(db) or row["public_code"]
        db.execute("UPDATE ddb_rows SET public_code=?, public_enabled=1 WHERE id=?", (code, rid))
        db.commit()
        log(db, "public_qr_new_code", f"ddb row {rid} {code}")
        db.commit()
        flash(f"New code created: {code}. The old printed QR code no longer works, print the new one.", "ok")
    return redirect(url_for("ddb.row_detail", rid=rid) + "#public")


@bp.route("/row/<int:rid>/qr")
@login_required
def row_qr(rid):
    db, row = _row(rid)
    if not row["public_code"]:
        abort(404)
    url = url_for("ddb.row_code_page", code=row["public_code"], _external=True)
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (row["tab_id"],)).fetchone() if row["tab_id"] else None
    title = (tab["name"] if tab else "Department Database") + f" · row #{row['id']}"
    item = {"id": "", "title": title, "dept": row["department_name"], "svg": _qr_svg(url), "url": url,
            "code": row["public_code"]}
    return render_template("qr_label.html", items=[item], many=False)


# ---------------------------------------------------------------- find a row by its public code (login-only)
def _row_by_code(db, code):
    """Find a Department Database row by its random HRC-##### public code."""
    wanted = parse_code_text(code)
    if not wanted:
        s = (code or "").strip()
        if s.isdigit() and len(s) == 5:
            wanted = f"HRC-{s}"
    if not wanted:
        return None, None
    row = db.execute("SELECT r.*, u.full_name AS owner_name, d.name AS department_name FROM ddb_rows r "
                     "JOIN users u ON u.id=r.owner_id JOIN departments d ON d.id=r.department_id "
                     "WHERE r.public_code=? AND r.deleted_at IS NULL", (wanted,)).fetchone()
    return wanted, row


@bp.route("/row/code/<code>")
@login_required
def row_code_page(code):
    """The public page for one Department Database row, opened by its share
    code (HRC-#####) from the Search QR page or by scanning its QR."""
    db = get_db()
    wanted, row = _row_by_code(db, code)
    if row is None:
        return render_template("deptdb_row_code.html", code=wanted or code, status="missing", row=None,
                               cols=[], vals={}, tab=None), 404
    if not row["public_enabled"]:
        return render_template("deptdb_row_code.html", code=row["public_code"],
                               status="off", row=row, cols=[], vals={}, tab=None), 410
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (row["tab_id"],)).fetchone() if row["tab_id"] else None
    cols = ddb_columns(db, row["department_id"], tab_id=row["tab_id"]) if row["tab_id"] else []
    _vmap, _urls = _display_map(db, [row], cols)
    db.execute("UPDATE ddb_rows SET public_views=public_views+1 WHERE id=?", (row["id"],))
    db.commit()
    return render_template("deptdb_row_code.html", code=row["public_code"],
                           status="ok", row=row, cols=cols, vals=_vmap[row["id"]], tab=tab)


@bp.route("/row/code/<code>/pdf")
@login_required
def row_code_pdf(code):
    """The same row as a clean PDF: its fields only, no history."""
    db = get_db()
    _wanted, row = _row_by_code(db, code)
    if row is None or not row["public_enabled"]:
        abort(404)
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (row["tab_id"],)).fetchone() if row["tab_id"] else None
    cols = ddb_columns(db, row["department_id"], tab_id=row["tab_id"]) if row["tab_id"] else []
    _vmap, _urls = _display_map(db, [row], cols)
    vals = _vmap[row["id"]]
    sections = [("", ["Field", "Value"],
                 [[c["name"], str(vals.get(c["id"]) or "")] for c in cols] or [["", "Nothing to show"]])]
    title = (tab["name"] if tab else "Department Database") + f" · row #{row['id']}"
    data = exports.document_pdf(title, f"Printed by {g.user['full_name']}", sections,
                                setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME))
    log(db, "code_pdf", row["public_code"])
    db.commit()
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{row["public_code"]}.pdf"'
    return resp


@bp.route("/row/<int:rid>/share", methods=["POST"])
@login_required
def row_share(rid):
    db, row = _row(rid)
    is_admin = ddb_is_tab_admin(db, g.user, row["department_id"])
    if row["deleted_at"] or not (row["owner_id"] == g.user["id"] or is_admin):
        abort(403)
    dept = db.execute("SELECT * FROM departments WHERE id=?", (row["department_id"],)).fetchone()
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (row["tab_id"],)).fetchone() if row["tab_id"] else None
    tab_name = tab["name"] if tab else ""
    row_dept = dept
    kind = request.form.get("kind")
    perm = request.form.get("permission", "view")
    if perm not in ("view", "edit"):
        perm = "view"
    if kind == "department":
        did = request.form.get("department_id", type=int)
        dept = db.execute("SELECT * FROM departments WHERE id=?", (did,)).fetchone() if did else None
        if dept is None:
            flash("Choose a department.", "error")
        elif did == row["department_id"]:
            flash("That department can already see this row.", "error")
        else:
            db.execute("DELETE FROM ddb_row_shares WHERE row_id=? AND department_id=?", (rid, did))
            db.execute("INSERT INTO ddb_row_shares(row_id,department_id,permission,created_by) VALUES (?,?,?,?)",
                       (rid, did, perm, g.user["id"]))
            ddb_history(db, rid, g.user, "shared", new=f"{dept['name']} ({'Can edit' if perm == 'edit' else 'View only'})")
            log(db, "ddb_share", f"row {rid} shared with {dept['name']} ({perm})")
            notify_ddb_task(db, g.user, row_dept,
                            f"{g.user['full_name']} shared a row in the tab '{tab_name}' in {row_dept['name']} with {dept['name']}.",
                            ddb_row_link(db, rid))
            db.commit()
            flash(f"Shared with {dept['name']} ({'Can edit' if perm == 'edit' else 'View only'}).", "ok")
    elif kind == "user":
        uid = request.form.get("user_id", type=int)
        user = db.execute("SELECT * FROM users WHERE id=? AND is_active=1", (uid,)).fetchone() if uid else None
        if user is None:
            flash("Choose a user.", "error")
        else:
            db.execute("DELETE FROM ddb_row_shares WHERE row_id=? AND user_id=?", (rid, uid))
            db.execute("INSERT INTO ddb_row_shares(row_id,user_id,permission,created_by) VALUES (?,?,?,?)",
                       (rid, uid, perm, g.user["id"]))
            notify(db, [uid], f"A department-database row was shared with you ({'Can edit' if perm == 'edit' else 'View only'}).",
                   ddb_row_link(db, rid), skip=g.user["id"])
            ddb_history(db, rid, g.user, "shared", new=f"{user['full_name']} ({'Can edit' if perm == 'edit' else 'View only'})")
            log(db, "ddb_share", f"row {rid} shared with {user['username']} ({perm})")
            notify_ddb_task(db, g.user, row_dept,
                            f"{g.user['full_name']} shared a row in the tab '{tab_name}' in {row_dept['name']} with {user['full_name']}.",
                            ddb_row_link(db, rid))
            db.commit()
            flash(f"Shared with {user['full_name']} ({'Can edit' if perm == 'edit' else 'View only'}).", "ok")
    else:
        flash("Choose whether to share with a department or a user.", "error")
    return redirect(url_for("ddb.row_detail", rid=rid))


@bp.route("/row/<int:rid>/share/<int:sid>/delete", methods=["POST"])
@login_required
def row_share_delete(rid, sid):
    db, row = _row(rid)
    is_admin = ddb_is_tab_admin(db, g.user, row["department_id"])
    if not (row["owner_id"] == g.user["id"] or is_admin):
        abort(403)
    db.execute("DELETE FROM ddb_row_shares WHERE id=? AND row_id=?", (sid, rid))
    ddb_history(db, rid, g.user, "unshared")
    log(db, "ddb_unshare", f"row {rid} share {sid} removed")
    dept = db.execute("SELECT * FROM departments WHERE id=?", (row["department_id"],)).fetchone()
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (row["tab_id"],)).fetchone() if row["tab_id"] else None
    notify_ddb_task(db, g.user, dept,
                    f"{g.user['full_name']} stopped sharing a row in the tab '{tab['name'] if tab else ''}' in {dept['name']}.",
                    ddb_row_link(db, rid))
    db.commit()
    flash("Share removed.", "ok")
    return redirect(url_for("ddb.row_detail", rid=rid))


def _form(dept, tab, cols, values, row=None, version=None, conflict=None, source=None):
    disp = dict(values or {})
    for c in cols:
        if c["col_type"] == "attachment":
            disp[c["id"]] = ddb_display_value(c, disp.get(c["id"]))
    return render_template("deptdb_form.html", dept=dept, tab=tab, cols=cols, values=disp, row=row,
                           version=version, conflict=conflict, source=source)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_row():
    db, dept, _is_admin = _dept()
    if not is_portal_admin(g.user) and g.user["department_id"] != dept["id"]:
        abort(403)
    tab, _tabs = _get_tab(db, dept, request.values.get("tab", type=int))
    if tab is None:
        flash("This department database has no tabs yet. Ask the department admin to create one.", "error")
        return redirect(url_for("ddb.index", **_back(dept)))
    cols = ddb_columns(db, dept["id"], tab_id=tab["id"])
    if not cols:
        flash(f"The '{tab['name']}' tab has no columns yet. Ask the department admin to add them.", "error")
        return redirect(url_for("ddb.index", **_back(dept, tab)))
    source = request.values.get("from_record", type=int)
    rec = None
    if source:
        from routes_records import _load as load_record
        rec, _lvl = load_record(source, "view")
    if request.method == "POST":
        values, errors = parse_form(cols, request.form)
        ferr, saved, _td = _handle_ddb_files(dept, cols, values, {})
        errors += ferr
        if errors:
            _delete_ddb_files(saved)
            for e in errors:
                flash(e, "error")
            return _form(dept, tab, cols, values, source=source)
        rid = ddb_create_row(db, g.user, dept["id"], values, tab_id=tab["id"], source_record_id=rec["id"] if rec else None)
        log(db, "ddb_add", f"{dept['name']} / {tab['name']} row {rid}")
        notify_ddb_task(db, g.user, dept,
                        f"{g.user['full_name']} added a row to the tab '{tab['name']}' in {dept['name']}.",
                        ddb_row_link(db, rid))
        db.commit()
        flash("Row added to the department database.", "ok")
        return redirect(url_for("ddb.row_detail", rid=rid))
    return _form(dept, tab, cols, ddb_prefill_from_record(db, rec, cols) if rec else {}, source=source)


@bp.route("/row/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def edit_row(rid):
    db, row = _row(rid)
    if row["deleted_at"] or not ddb_can_edit_row(db, g.user, row):
        abort(403)
    dept = db.execute("SELECT * FROM departments WHERE id=?", (row["department_id"],)).fetchone()
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (row["tab_id"],)).fetchone() if row["tab_id"] else None
    cols = ddb_columns(db, row["department_id"], tab_id=row["tab_id"]) if row["tab_id"] else []
    old = ddb_values(db, [rid])[rid]
    if request.method == "POST":
        values, errors = parse_form(cols, request.form, old)
        ferr, saved, to_delete = _handle_ddb_files(dept, cols, values, old)
        errors += ferr
        version = request.form.get("version", type=int) or 0
        if errors:
            _delete_ddb_files(saved)
            for e in errors:
                flash(e, "error")
            return _form(dept, tab, cols, values, row, version)
        result = ddb_update_row(db, g.user, row, cols, values, version)
        if result == "ok":
            _delete_ddb_files(to_delete)
        if result == "conflict":
            latest = ddb_values(db, [rid])[rid]
            fresh = db.execute("SELECT * FROM ddb_rows WHERE id=?", (rid,)).fetchone()
            last = db.execute("SELECT full_name, at FROM ddb_history WHERE row_id=? ORDER BY id DESC LIMIT 1",
                              (rid,)).fetchone()
            mine = [(c["name"], values[c["id"]] or "") for c in cols
                    if (values[c["id"]] or None) != (latest.get(c["id"]) or None)]
            flash("This row was changed by someone else while you were editing. Your changes were NOT saved.", "error")
            return _form(dept, tab, cols, latest, fresh, fresh["version"],
                         {"by": last["full_name"] if last else "Someone", "at": last["at"] if last else "",
                          "mine": mine})
        if result == "nochange":
            flash("There was nothing to change.", "ok")
        else:
            log(db, "ddb_edit", f"{dept['name']} row {rid}")
            notify_ddb_task(db, g.user, dept,
                            f"{g.user['full_name']} edited a row in the tab '{tab['name'] if tab else ''}' in {dept['name']}.",
                            ddb_row_link(db, rid))
            db.commit()
            flash("Changes saved.", "ok")
        return redirect(url_for("ddb.row_detail", rid=rid))
    return _form(dept, tab, cols, old, row, row["version"])


@bp.route("/row/<int:rid>/delete", methods=["POST"])
@login_required
def delete_row(rid):
    db, row = _row(rid)
    if row["deleted_at"] or not ddb_can_delete_row(db, g.user, row):
        abort(403)
    db.execute("UPDATE ddb_rows SET deleted_at=datetime('now','localtime') WHERE id=?", (rid,))
    ddb_history(db, rid, g.user, "deleted")
    log(db, "ddb_delete", f"row {rid}")
    dept = db.execute("SELECT * FROM departments WHERE id=?", (row["department_id"],)).fetchone()
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (row["tab_id"],)).fetchone() if row["tab_id"] else None
    notify_ddb_task(db, g.user, dept,
                    f"{g.user['full_name']} deleted a row from the tab '{tab['name'] if tab else ''}' in {dept['name']}.",
                    url_for("ddb.index", dept=dept["id"], tab=tab["id"] if tab else None))
    db.commit()
    flash("Row deleted. A department admin can restore it for %d days." % config.BIN_DAYS, "ok")
    return redirect(url_for("ddb.index", dept=row["department_id"]) if is_portal_admin(g.user)
                    else url_for("ddb.index"))


@bp.route("/row/<int:rid>/restore", methods=["POST"])
@login_required
def restore_row(rid):
    db, row = _row(rid)
    if not ddb_is_tab_admin(db, g.user, row["department_id"]) or not row["deleted_at"]:
        abort(403)
    db.execute("UPDATE ddb_rows SET deleted_at=NULL, version=version+1 WHERE id=?", (rid,))
    ddb_history(db, rid, g.user, "restored")
    log(db, "ddb_restore", f"row {rid}")
    dept = db.execute("SELECT * FROM departments WHERE id=?", (row["department_id"],)).fetchone()
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (row["tab_id"],)).fetchone() if row["tab_id"] else None
    notify_ddb_task(db, g.user, dept,
                    f"{g.user['full_name']} restored a row in the tab '{tab['name'] if tab else ''}' in {dept['name']}.",
                    ddb_row_link(db, rid))
    db.commit()
    flash("Row restored.", "ok")
    return redirect(url_for("ddb.row_detail", rid=rid))


# ---------------------------------------------------------------- columns (per tab, admins / delegates)
def _clean_options(ctype, text):
    options = "\n".join(dict.fromkeys(o.strip() for o in (text or "").splitlines() if o.strip()))
    return options if ctype == "dropdown" else None


@bp.route("/columns")
@login_required
def columns():
    db, dept = _tab_admin()
    if request.args.get("tab") == "invoices":
        return _invoice_tab_view(db, dept, is_admin, request.args)
    tab, tabs = _get_tab(db, dept, request.args.get("tab", type=int))
    if tab is None:
        flash("Create a tab first.", "error")
        return redirect(url_for("ddb.tabs", **_back(dept)))
    cols = db.execute("SELECT c.*, (SELECT COUNT(*) FROM ddb_values v JOIN ddb_rows r ON r.id=v.row_id "
                      "WHERE v.column_id=c.id AND r.deleted_at IS NULL) AS used FROM ddb_columns c "
                      "WHERE c.tab_id=? AND c.removed_at IS NULL ORDER BY c.position, c.id",
                      (tab["id"],)).fetchall()
    removed = db.execute("SELECT * FROM ddb_columns WHERE tab_id=? AND removed_at IS NOT NULL "
                         "ORDER BY removed_at DESC", (tab["id"],)).fetchall()
    return render_template("deptdb_columns.html", dept=dept, tab=tab, tabs=tabs, cols=cols, removed=removed, types=DDB_COLUMN_TYPES,
                           type_label=DDB_TYPE_LABEL, can_create_attachment=_can_create_attachment(g.user, dept["id"]))


@bp.route("/columns/add", methods=["POST"])
@login_required
def column_add():
    db, dept = _tab_admin()
    tab, _tabs = _get_tab(db, dept, request.form.get("tab", type=int))
    if tab is None:
        flash("Choose a tab first.", "error")
        return redirect(url_for("ddb.tabs", **_back(dept)))
    name = " ".join((request.form.get("name") or "").split())[:60]
    ctype = request.form.get("col_type", "text")
    options = _clean_options(ctype, request.form.get("options"))
    if not name:
        flash("Type the column name.", "error")
    elif ctype == "attachment" and not _can_create_attachment(g.user, dept["id"]):
        flash("Only a dept admin given attachment-column access by the portal admin can create an attachment column.", "error")
    elif ctype not in DDB_TYPE_LABEL:
        flash("Choose a column type.", "error")
    elif ctype == "dropdown" and not options:
        flash("A dropdown needs at least one option (one per line).", "error")
    else:
        pos = db.execute("SELECT COALESCE(MAX(position),-1)+1 FROM ddb_columns WHERE tab_id=?",
                         (tab["id"],)).fetchone()[0]
        try:
            db.execute("INSERT INTO ddb_columns(department_id,tab_id,name,col_type,options,required,has_time,position) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (dept["id"], tab["id"], name, ctype, options, 1 if request.form.get("required") else 0,
                        1 if (request.form.get("has_time") and ctype == "date") else 0, pos))
            log(db, "ddb_column_add", f"{dept['name']} / {tab['name']}: {name}")
            notify_ddb_task(db, g.user, dept,
                            f"{g.user['full_name']} added the column '{name}' to the tab '{tab['name']}' in {dept['name']}.",
                            url_for("ddb.index", dept=dept["id"], tab=tab["id"]))
            db.commit()
            flash(f"Column '{name}' added.", "ok")
        except sqlite3.IntegrityError:
            db.rollback()
            exists = db.execute("SELECT 1 FROM ddb_columns WHERE tab_id=? AND lower(name)=lower(?) AND removed_at IS NULL",
                                (tab["id"], name)).fetchone()
            flash(f"A column named '{name}' already exists in this tab." if exists else "Column could not be added. Check the type is allowed for this database.", "error")
    return redirect(url_for("ddb.columns", **_back(dept, tab)))


def _ddb_column(cid):
    db = get_db()
    col = db.execute("SELECT * FROM ddb_columns WHERE id=?", (cid,)).fetchone()
    if col is None:
        abort(404)
    if not ddb_is_tab_admin(db, g.user, col["department_id"]):
        abort(403)
    dept = db.execute("SELECT * FROM departments WHERE id=?", (col["department_id"],)).fetchone()
    tab = db.execute("SELECT * FROM ddb_tabs WHERE id=?", (col["tab_id"],)).fetchone() if col["tab_id"] else None
    return db, col, dept, tab


@bp.route("/columns/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def column_edit(cid):
    db, col, dept, tab = _ddb_column(cid)
    if request.method == "POST":
        name = " ".join((request.form.get("name") or "").split())[:60]
        options = _clean_options(col["col_type"], request.form.get("options"))
        if not name:
            flash("Type the column name.", "error")
        elif col["col_type"] == "dropdown" and not options:
            flash("A dropdown needs at least one option.", "error")
        else:
            try:
                db.execute("UPDATE ddb_columns SET name=?, options=?, required=?, shown=?, has_time=? WHERE id=?",
                           (name, options, 1 if request.form.get("required") else 0,
                            1 if request.form.get("shown") else 0,
                            1 if (request.form.get("has_time") and col["col_type"] == "date") else 0, cid))
                log(db, "ddb_column_edit", f"{dept['name']}: {name}")
                notify_ddb_task(db, g.user, dept,
                                f"{g.user['full_name']} renamed the column '{col['name']}' to '{name}' in the tab '{tab['name'] if tab else ''}' in {dept['name']}.",
                                url_for("ddb.index", dept=dept["id"], tab=tab["id"] if tab else None))
                db.commit()
                flash("Column saved.", "ok")
                return redirect(url_for("ddb.columns", **_back(dept, tab)))
            except sqlite3.IntegrityError:
                db.rollback()
                flash(f"A column named '{name}' already exists in this tab.", "error")
    return render_template("deptdb_column_edit.html", col=col, dept=dept, tab=tab, type_label=DDB_TYPE_LABEL)


@bp.route("/columns/<int:cid>/remove", methods=["POST"])
@login_required
def column_remove(cid):
    db, col, dept, tab = _ddb_column(cid)
    db.execute("UPDATE ddb_columns SET removed_at=datetime('now','localtime') WHERE id=?", (cid,))
    log(db, "ddb_column_remove", f"{dept['name']}: {col['name']}")
    notify_ddb_task(db, g.user, dept,
                    f"{g.user['full_name']} removed the column '{col['name']}' from the tab '{tab['name'] if tab else ''}' in {dept['name']}.",
                    url_for("ddb.index", dept=dept["id"], tab=tab["id"] if tab else None))
    db.commit()
    flash(f"Column '{col['name']}' removed. Its data is kept and it can be restored.", "ok")
    return redirect(url_for("ddb.columns", **_back(dept, tab)))


@bp.route("/columns/<int:cid>/restore", methods=["POST"])
@login_required
def column_restore(cid):
    db, col, dept, tab = _ddb_column(cid)
    try:
        db.execute("UPDATE ddb_columns SET removed_at=NULL WHERE id=?", (cid,))
        log(db, "ddb_column_restore", f"{dept['name']}: {col['name']}")
        notify_ddb_task(db, g.user, dept,
                        f"{g.user['full_name']} restored the column '{col['name']}' in the tab '{tab['name'] if tab else ''}' in {dept['name']}.",
                        url_for("ddb.index", dept=dept["id"], tab=tab["id"] if tab else None))
        db.commit()
        flash(f"Column '{col['name']}' restored.", "ok")
    except sqlite3.IntegrityError:
        db.rollback()
        flash(f"A column named '{col['name']}' exists already. Rename it first, then restore.", "error")
    return redirect(url_for("ddb.columns", **_back(dept, tab)))


@bp.route("/columns/<int:cid>/move", methods=["POST"])
@login_required
def column_move(cid):
    db, col, dept, tab = _ddb_column(cid)
    cols = [r["id"] for r in db.execute("SELECT id FROM ddb_columns WHERE tab_id=? AND removed_at IS NULL "
                                        "ORDER BY position, id", (col["tab_id"],))]
    i = cols.index(cid) if cid in cols else -1
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if i >= 0 and 0 <= j < len(cols):
        cols[i], cols[j] = cols[j], cols[i]
        for pos, c in enumerate(cols):
            db.execute("UPDATE ddb_columns SET position=? WHERE id=?", (pos, c))
        notify_ddb_task(db, g.user, dept,
                        f"{g.user['full_name']} moved the column '{col['name']}' in the tab '{tab['name'] if tab else ''}' in {dept['name']}.",
                        url_for("ddb.index", dept=dept["id"], tab=tab["id"] if tab else None))
        db.commit()
    return redirect(url_for("ddb.columns", **_back(dept, tab)))


@bp.route("/attachment/<int:rid>/<int:cid>")
@login_required
def download_attachment(rid, cid):
    db, row = _row(rid)
    col = db.execute("SELECT * FROM ddb_columns WHERE id=? AND department_id=?", (cid, row["department_id"])).fetchone()
    if col is None or col["col_type"] != "attachment":
        abort(404)
    vals = ddb_values(db, [rid])[rid]
    info = ddb_attachment_info(vals.get(cid))
    if info is None:
        abort(404)
    path = _ddb_file_path(info["stored"])
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=info["original"])


# Old "People and access" page: levels no longer exist — visibility is
# department-wide and editing is owner-only (plus shares). Keep the URL
# working by sending it to the delegates page.
@bp.route("/people", methods=["GET", "POST"])
@login_required
def people():
    db, dept = _tab_admin()
    return redirect(url_for("ddb.delegates", **_back(dept)))
