"""
routes_deptdb.py - the DEPARTMENT DATABASE: one shared table per department.

The department admin (or a person he made "manager") decides the columns and who may do
what. Normal users add their own rows (also copied from a personal record) and keep them up
to date. Every change is written in the row's history, and two people saving the same row
at the same time cannot overwrite each other.

Levels (see core.DDB_LEVELS):  view | own (default) | edit | manager.
The portal admin and the department admin are always managers.

Used by: app.py (registers it).   Uses: core.py, auth.py, models.py, exports.py
Templates: deptdb, deptdb_form, deptdb_row, deptdb_columns, deptdb_column_edit, deptdb_people.
"""
import sqlite3

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import config
import exports
from auth import login_required
from core import (COLUMN_TYPES, DDB_LEVELS, DDB_LEVEL_WORDS, TYPE_LABEL, ddb_can_delete_row, ddb_can_edit_row,
                  ddb_columns, ddb_create_row, ddb_history, ddb_level, ddb_prefill_from_record, ddb_update_row,
                  ddb_values, format_code, notify, parse_code, parse_form, show_when)
from models import get_db, log, setting_get
from utils import csv_response, like_pattern, page_info

bp = Blueprint("ddb", __name__, url_prefix="/deptdb")


# ---------------------------------------------------------------- which department, which level
def _dept():
    """(db, department row, level) of the department database being used. A normal user always
    uses his own department; the portal admin may pick any with ?dept=."""
    db = get_db()
    dept_id = g.user["department_id"]
    if g.user["role"] == "admin":
        dept_id = request.values.get("dept", type=int) or dept_id
    dept = db.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone() if dept_id else None
    if dept is None:
        flash("You are not in a department yet. Ask the admin.", "error")
        abort(403)
    level = ddb_level(db, g.user, dept["id"])
    if level is None:
        abort(403)
    return db, dept, level


def _manager():
    db, dept, level = _dept()
    if level != "manager":
        abort(403)
    return db, dept


def _row(rid, dept_id=None):
    db = get_db()
    row = db.execute("SELECT r.*, u.full_name AS owner_name, d.name AS department_name FROM ddb_rows r "
                     "JOIN users u ON u.id=r.owner_id JOIN departments d ON d.id=r.department_id "
                     "WHERE r.id=?", (rid,)).fetchone()
    if row is None:
        abort(404)
    level = ddb_level(db, g.user, row["department_id"])
    if level is None:
        abort(404)
    if row["deleted_at"] and level != "manager":
        abort(404)
    return db, row, level


def _back(dept):
    return {"dept": dept["id"]} if g.user["role"] == "admin" else {}


# ---------------------------------------------------------------- list, search, filter, sort
def _filters(db, dept, level, args):
    """WHERE text, params, ORDER BY text, order params and the 'info' of the list bar."""
    where, params = ["r.department_id=?"], [dept["id"]]
    deleted = bool(args.get("deleted")) and level == "manager"
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
                     "AND c.removed_at IS NULL WHERE v.row_id=r.id AND c.department_id=? "
                     "AND lower(c.name)=lower(?) AND v.value LIKE ? ESCAPE '\\')")
        params += [dept["id"], fcol, like_pattern(fval)]
    sort = args.get("sort", "updated")
    direction = "asc" if args.get("dir") == "asc" else "desc"
    d = "ASC" if direction == "asc" else "DESC"
    order, op = f"r.updated_at {d}, r.id {d}", []
    if sort == "created":
        order = f"r.created_at {d}, r.id {d}"
    elif sort.startswith("col:"):
        name = sort[4:]
        numeric = db.execute("SELECT 1 FROM ddb_columns WHERE department_id=? AND lower(name)=lower(?) "
                             "AND col_type='number' AND removed_at IS NULL", (dept["id"], name)).fetchone()
        sub = ("(SELECT v.value FROM ddb_values v JOIN ddb_columns c ON c.id=v.column_id AND c.removed_at IS NULL "
               "WHERE v.row_id=r.id AND c.department_id=? AND lower(c.name)=lower(?) LIMIT 1)")
        expr = f"CAST({sub} AS REAL)" if numeric else f"{sub} COLLATE NOCASE"
        order = f"({sub} IS NULL), {expr} {d}, r.id DESC"
        op = [dept["id"], name, dept["id"], name]
    else:
        sort = "updated"
    info = {"sort": sort, "dir": direction, "fcol": fcol, "fval": fval}
    return " AND ".join(where), params, order, op, info, q, mine, deleted


@bp.route("")
@login_required
def index():
    db, dept, level = _dept()
    number = parse_code(request.args.get("q"))
    if number is not None:                                   # typing HRC-12 opens that QR code
        return redirect(url_for("public.code_page", code=format_code(number)))
    where, params, order, op, info, q, mine, deleted = _filters(db, dept, level, request.args)
    total = db.execute("SELECT COUNT(*) FROM ddb_rows r WHERE " + where, params).fetchone()[0]
    page, pages, offset = page_info(total, request.args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute("SELECT r.*, u.full_name AS owner_name FROM ddb_rows r JOIN users u ON u.id=r.owner_id "
                      "WHERE " + where + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                      params + op + [config.PER_PAGE, offset]).fetchall()
    cols = ddb_columns(db, dept["id"])
    counts = {
        "all": db.execute("SELECT COUNT(*) FROM ddb_rows WHERE department_id=? AND deleted_at IS NULL",
                          (dept["id"],)).fetchone()[0],
        "mine": db.execute("SELECT COUNT(*) FROM ddb_rows WHERE department_id=? AND deleted_at IS NULL "
                           "AND owner_id=?", (dept["id"], g.user["id"])).fetchone()[0],
        "deleted": db.execute("SELECT COUNT(*) FROM ddb_rows WHERE department_id=? AND deleted_at IS NOT NULL",
                              (dept["id"],)).fetchone()[0] if level == "manager" else 0}
    keep = {k: v for k, v in request.args.items() if k not in ("page", "dept")}
    return render_template(
        "deptdb.html", dept=dept, level=level, level_word=DDB_LEVEL_WORDS[level], cols=cols, rows=rows,
        vmap=ddb_values(db, [r["id"] for r in rows]), info=info, q=q, mine=mine, deleted=deleted,
        total=total, page=page, pages=pages, counts=counts, keep=keep,
        can_add=level in ("own", "edit", "manager") and bool(cols),
        names=[c["name"] for c in cols],
        depts=db.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        if g.user["role"] == "admin" else [],
        can_edit_row=lambda r: ddb_can_edit_row(level, g.user, r),
        can_delete_row=lambda r: ddb_can_delete_row(level, g.user, r))


@bp.route("/export")
@login_required
def export():
    db, dept, level = _dept()
    where, params, order, op, _info, _q, _mine, _deleted = _filters(db, dept, level, request.args)
    rows = db.execute("SELECT r.*, u.full_name AS owner_name FROM ddb_rows r JOIN users u ON u.id=r.owner_id "
                      "WHERE " + where + " ORDER BY " + order, params + op).fetchall()
    cols = ddb_columns(db, dept["id"])
    vals = ddb_values(db, [r["id"] for r in rows])
    header = [c["name"] for c in cols] + ["Added by", "Last updated"]
    out = [[(show_when(vals[r["id"]].get(c["id"])) if c["col_type"] == "date" else vals[r["id"]].get(c["id"]))
            for c in cols] + [r["owner_name"], r["updated_at"]] for r in rows]
    kinds = ["number" if c["col_type"] == "number" else "text" for c in cols] + ["text", "text"]
    fmt = request.args.get("fmt", "xlsx")
    log(db, "export", f"department database {dept['name']}: {fmt}, {len(rows)} rows")
    db.commit()
    if fmt == "csv":
        return csv_response(header, out, "department_database_" + dept["name"])
    return exports.table_file("pdf" if fmt == "pdf" else "xlsx", f"{dept['name']} database", header, out, kinds,
                              f"{len(rows)} rows", setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME),
                              "department_database_" + dept["name"])


# ---------------------------------------------------------------- one row
@bp.route("/row/<int:rid>")
@login_required
def row_detail(rid):
    db, row, level = _row(rid)
    cols = ddb_columns(db, row["department_id"])
    return render_template(
        "deptdb_row.html", row=row, level=level, cols=cols, vals=ddb_values(db, [rid])[rid],
        history=db.execute("SELECT * FROM ddb_history WHERE row_id=? ORDER BY id DESC LIMIT 100", (rid,)).fetchall(),
        can_edit=ddb_can_edit_row(level, g.user, row) and not row["deleted_at"],
        can_delete=ddb_can_delete_row(level, g.user, row) and not row["deleted_at"],
        can_restore=level == "manager" and bool(row["deleted_at"]))


def _form(dept, cols, values, row=None, version=None, conflict=None, source=None):
    return render_template("deptdb_form.html", dept=dept, cols=cols, values=values, row=row,
                           version=version, conflict=conflict, source=source)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_row():
    db, dept, level = _dept()
    cols = ddb_columns(db, dept["id"])
    if level not in ("own", "edit", "manager"):
        abort(403)
    if not cols:
        flash("This department database has no columns yet. Ask the department admin to add them.", "error")
        return redirect(url_for("ddb.index", **_back(dept)))
    source = request.values.get("from_record", type=int)
    rec = None
    if source:                                                # "Copy to department database" on a record
        from routes_records import _load as load_record      # (late import: avoids a circular import)
        rec, _lvl = load_record(source, "view")
    if request.method == "POST":
        values, errors = parse_form(cols, request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            return _form(dept, cols, values, source=source)
        rid = ddb_create_row(db, g.user, dept["id"], values, rec["id"] if rec else None)
        log(db, "ddb_add", f"{dept['name']} row {rid}")
        db.commit()
        flash("Row added to the department database.", "ok")
        return redirect(url_for("ddb.row_detail", rid=rid))
    return _form(dept, cols, ddb_prefill_from_record(db, rec, cols) if rec else {}, source=source)


@bp.route("/row/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def edit_row(rid):
    db, row, level = _row(rid)
    if row["deleted_at"] or not ddb_can_edit_row(level, g.user, row):
        abort(403)
    dept = db.execute("SELECT * FROM departments WHERE id=?", (row["department_id"],)).fetchone()
    cols = ddb_columns(db, row["department_id"])
    old = ddb_values(db, [rid])[rid]
    if request.method == "POST":
        values, errors = parse_form(cols, request.form, old)
        version = request.form.get("version", type=int) or 0
        if errors:
            for e in errors:
                flash(e, "error")
            return _form(dept, cols, values, row, version)
        result = ddb_update_row(db, g.user, row, cols, values, version)
        if result == "conflict":
            latest = ddb_values(db, [rid])[rid]
            fresh = db.execute("SELECT * FROM ddb_rows WHERE id=?", (rid,)).fetchone()
            last = db.execute("SELECT full_name, at FROM ddb_history WHERE row_id=? ORDER BY id DESC LIMIT 1",
                              (rid,)).fetchone()
            mine = [(c["name"], values[c["id"]] or "") for c in cols
                    if (values[c["id"]] or None) != (latest.get(c["id"]) or None)]
            flash("This row was changed by someone else while you were editing. Your changes were NOT saved.", "error")
            return _form(dept, cols, latest, fresh, fresh["version"],
                         {"by": last["full_name"] if last else "Someone", "at": last["at"] if last else "",
                          "mine": mine})
        if result == "nochange":
            flash("There was nothing to change.", "ok")
        else:
            log(db, "ddb_edit", f"{dept['name']} row {rid}")
            db.commit()
            flash("Changes saved.", "ok")
        return redirect(url_for("ddb.row_detail", rid=rid))
    return _form(dept, cols, old, row, row["version"])


@bp.route("/row/<int:rid>/delete", methods=["POST"])
@login_required
def delete_row(rid):
    db, row, level = _row(rid)
    if row["deleted_at"] or not ddb_can_delete_row(level, g.user, row):
        abort(403)
    db.execute("UPDATE ddb_rows SET deleted_at=datetime('now','localtime') WHERE id=?", (rid,))
    ddb_history(db, rid, g.user, "deleted")
    log(db, "ddb_delete", f"row {rid}")
    db.commit()
    flash("Row deleted. A manager can restore it for %d days." % config.BIN_DAYS, "ok")
    return redirect(url_for("ddb.index", dept=row["department_id"]) if g.user["role"] == "admin"
                    else url_for("ddb.index"))


@bp.route("/row/<int:rid>/restore", methods=["POST"])
@login_required
def restore_row(rid):
    db, row, level = _row(rid)
    if level != "manager" or not row["deleted_at"]:
        abort(403)
    db.execute("UPDATE ddb_rows SET deleted_at=NULL, version=version+1 WHERE id=?", (rid,))
    ddb_history(db, rid, g.user, "restored")
    log(db, "ddb_restore", f"row {rid}")
    db.commit()
    flash("Row restored.", "ok")
    return redirect(url_for("ddb.row_detail", rid=rid))


# ---------------------------------------------------------------- columns (managers)
def _clean_options(ctype, text):
    options = "\n".join(dict.fromkeys(o.strip() for o in (text or "").splitlines() if o.strip()))
    return options if ctype == "dropdown" else None


@bp.route("/columns")
@login_required
def columns():
    db, dept = _manager()
    cols = db.execute("SELECT c.*, (SELECT COUNT(*) FROM ddb_values v JOIN ddb_rows r ON r.id=v.row_id "
                      "WHERE v.column_id=c.id AND r.deleted_at IS NULL) AS used FROM ddb_columns c "
                      "WHERE c.department_id=? AND c.removed_at IS NULL ORDER BY c.position, c.id",
                      (dept["id"],)).fetchall()
    removed = db.execute("SELECT * FROM ddb_columns WHERE department_id=? AND removed_at IS NOT NULL "
                         "ORDER BY removed_at DESC", (dept["id"],)).fetchall()
    return render_template("deptdb_columns.html", dept=dept, cols=cols, removed=removed, types=COLUMN_TYPES,
                           type_label=TYPE_LABEL)


@bp.route("/columns/add", methods=["POST"])
@login_required
def column_add():
    db, dept = _manager()
    name = " ".join((request.form.get("name") or "").split())[:60]
    ctype = request.form.get("col_type", "text")
    options = _clean_options(ctype, request.form.get("options"))
    if not name:
        flash("Type the column name.", "error")
    elif ctype not in TYPE_LABEL:
        flash("Choose a column type.", "error")
    elif ctype == "dropdown" and not options:
        flash("A dropdown needs at least one option (one per line).", "error")
    else:
        pos = db.execute("SELECT COALESCE(MAX(position),-1)+1 FROM ddb_columns WHERE department_id=?",
                         (dept["id"],)).fetchone()[0]
        try:
            db.execute("INSERT INTO ddb_columns(department_id,name,col_type,options,required,has_time,position) "
                       "VALUES (?,?,?,?,?,?,?)",
                       (dept["id"], name, ctype, options, 1 if request.form.get("required") else 0,
                        1 if (request.form.get("has_time") and ctype == "date") else 0, pos))
            log(db, "ddb_column_add", f"{dept['name']}: {name}")
            db.commit()
            flash(f"Column '{name}' added.", "ok")
        except sqlite3.IntegrityError:
            db.rollback()
            flash(f"A column named '{name}' already exists.", "error")
    return redirect(url_for("ddb.columns", **_back(dept)))


def _ddb_column(cid):
    db = get_db()
    col = db.execute("SELECT * FROM ddb_columns WHERE id=?", (cid,)).fetchone()
    if col is None:
        abort(404)
    if ddb_level(db, g.user, col["department_id"]) != "manager":
        abort(403)
    dept = db.execute("SELECT * FROM departments WHERE id=?", (col["department_id"],)).fetchone()
    return db, col, dept


@bp.route("/columns/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def column_edit(cid):
    db, col, dept = _ddb_column(cid)
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
                db.commit()
                flash("Column saved.", "ok")
                return redirect(url_for("ddb.columns", **_back(dept)))
            except sqlite3.IntegrityError:
                db.rollback()
                flash(f"A column named '{name}' already exists.", "error")
    return render_template("deptdb_column_edit.html", col=col, dept=dept, type_label=TYPE_LABEL)


@bp.route("/columns/<int:cid>/remove", methods=["POST"])
@login_required
def column_remove(cid):
    db, col, dept = _ddb_column(cid)
    db.execute("UPDATE ddb_columns SET removed_at=datetime('now','localtime') WHERE id=?", (cid,))
    log(db, "ddb_column_remove", f"{dept['name']}: {col['name']}")
    db.commit()
    flash(f"Column '{col['name']}' removed. Its data is kept and it can be restored.", "ok")
    return redirect(url_for("ddb.columns", **_back(dept)))


@bp.route("/columns/<int:cid>/restore", methods=["POST"])
@login_required
def column_restore(cid):
    db, col, dept = _ddb_column(cid)
    try:
        db.execute("UPDATE ddb_columns SET removed_at=NULL WHERE id=?", (cid,))
        log(db, "ddb_column_restore", f"{dept['name']}: {col['name']}")
        db.commit()
        flash(f"Column '{col['name']}' restored.", "ok")
    except sqlite3.IntegrityError:
        db.rollback()
        flash(f"A column named '{col['name']}' exists already. Rename it first, then restore.", "error")
    return redirect(url_for("ddb.columns", **_back(dept)))


@bp.route("/columns/<int:cid>/move", methods=["POST"])
@login_required
def column_move(cid):
    db, col, dept = _ddb_column(cid)
    cols = [r["id"] for r in db.execute("SELECT id FROM ddb_columns WHERE department_id=? AND removed_at IS NULL "
                                        "ORDER BY position, id", (dept["id"],))]
    i = cols.index(cid) if cid in cols else -1
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if i >= 0 and 0 <= j < len(cols):
        cols[i], cols[j] = cols[j], cols[i]
        for pos, c in enumerate(cols):
            db.execute("UPDATE ddb_columns SET position=? WHERE id=?", (pos, c))
        db.commit()
    return redirect(url_for("ddb.columns", **_back(dept)))


# ---------------------------------------------------------------- who may do what (managers)
@bp.route("/people", methods=["GET", "POST"])
@login_required
def people():
    db, dept = _manager()
    members = db.execute("SELECT u.id, u.full_name, u.username, u.is_dept_admin, u.role, "
                         "COALESCE(p.level, 'own') AS level FROM users u "
                         "LEFT JOIN ddb_perms p ON p.user_id=u.id AND p.department_id=? "
                         "WHERE u.department_id=? AND u.is_active=1 ORDER BY u.full_name",
                         (dept["id"], dept["id"])).fetchall()
    if request.method == "POST":
        changed = 0
        for m in members:
            if m["is_dept_admin"] or m["role"] == "admin":
                continue                                        # they are managers by their role
            new = request.form.get(f"level_{m['id']}")
            if new not in DDB_LEVEL_WORDS or new == m["level"]:
                continue
            if new == "own":
                db.execute("DELETE FROM ddb_perms WHERE department_id=? AND user_id=?", (dept["id"], m["id"]))
            else:
                db.execute("INSERT INTO ddb_perms(department_id,user_id,level) VALUES (?,?,?) "
                           "ON CONFLICT(department_id,user_id) DO UPDATE SET level=excluded.level",
                           (dept["id"], m["id"], new))
            notify(db, [m["id"]], f"Your access to the {dept['name']} department database is now: "
                   f"{DDB_LEVEL_WORDS[new]}.", "/deptdb", skip=g.user["id"])
            log(db, "ddb_permission", f"{dept['name']}: {m['username']} -> {new}")
            changed += 1
        db.commit()
        flash(f"Saved. {changed} change(s)." if changed else "Nothing changed.", "ok")
        return redirect(url_for("ddb.people", **_back(dept)))
    return render_template("deptdb_people.html", dept=dept, members=members, levels=DDB_LEVELS)
