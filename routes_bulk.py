"""
routes_bulk.py - bulk actions on ticked records, Excel/PDF exports, reports, saved views.

Used by: app.py (registers it).
Uses:    core.py, exports.py, routes_records.py, routes_admin.py, auth.py, models.py
Templates: reports (the page); the bulk bar lives in records_list.html / admin_records.html.
"""
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import config
import exports
from auth import admin_required, login_required
from core import (MANAGE_LEVELS, show_when, PERM_WORDS, clean_permission, share_with_department, share_with_user, access_level, add_history, build_table, dept_member_ids, get_columns,
                  get_record, notify, rec_select, reminder_rows, search_clause, soft_delete,
                  summaries_for, values_for)
from models import get_db, log, setting_get
from routes_admin import _record_filters
from routes_records import (_load as load_record, available_tabs, list_options, tab_clause)
from utils import csv_response, is_portal_admin

bp = Blueprint("bulk", __name__)


def _company(db):
    return setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME)


def _safe_back(url):
    """Only go back to a page of this portal."""
    return url if (url or "").startswith("/") and not url.startswith("//") else url_for("records.list_records")


# ---------------------------------------------------------------- bulk actions
@bp.route("/records/bulk", methods=["POST"])
@login_required
def bulk():
    db = get_db()
    back = _safe_back(request.form.get("back"))
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    action = request.form.get("action", "")
    if not ids:
        flash("Tick at least one record first.", "error")
        return redirect(back)
    recs = [r for r in (get_record(db, i) for i in ids) if r and not r["deleted_at"]
            and access_level(db, g.user, r) is not None]
    mine = [r for r in recs if access_level(db, g.user, r) in MANAGE_LEVELS]

    if action == "share":
        names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM departments")}
        chosen = [int(x) for x in request.form.getlist("dept") if x.isdigit() and int(x) in names]
        perm = clean_permission(request.form.get("permission"))
        person = db.execute("SELECT * FROM users WHERE id=? AND is_active=1",
                            (request.form.get("user_id", type=int) or 0,)).fetchone()
        if not chosen and person is None:
            flash("Choose the departments or the person to share with.", "error")
            return redirect(back)
        for rec in mine:
            for d in chosen:
                share_with_department(db, g.user, rec, d, names[d], perm, quiet=True)
            if person is not None and person["id"] != rec["owner_id"]:
                share_with_user(db, g.user, rec, person, perm, quiet=True)
        if mine:                                       # one summary message instead of one per record
            for d in chosen:
                notify(db, dept_member_ids(db, d), f"{g.user['full_name']} shared {len(mine)} record(s) with your "
                       f"department ({PERM_WORDS[perm]}).", "/records?tab=shared_with_me", skip=g.user["id"])
            if person is not None:
                notify(db, [person["id"]], f"{g.user['full_name']} shared {len(mine)} record(s) with you "
                       f"({PERM_WORDS[perm]}).", "/records?tab=shared_with_me", skip=g.user["id"])
        log(db, "bulk_share", f"{len(mine)} records ({perm})")
        db.commit()
        flash(f"{len(mine)} record(s) shared ({PERM_WORDS[perm]}). Records you do not own were skipped.", "ok")
    elif action == "delete":
        for rec in mine:
            soft_delete(db, g.user, rec)
        log(db, "bulk_delete", f"{len(mine)} records")
        db.commit()
        flash(f"{len(mine)} record(s) moved to the recycle bin.", "ok")
    elif action == "public":
        return redirect(url_for("public.link_new", ids=",".join(str(r["id"]) for r in mine)))
    elif action in ("xlsx", "pdf", "csv"):
        with_owner = any(r["owner_id"] != g.user["id"] for r in recs)
        header, rows, kinds = build_table(db, recs, with_owner)
        log(db, "export", f"{action}: {len(recs)} selected records")
        db.commit()
        if action == "csv":
            return csv_response(header, rows, "selected_records")
        return exports.table_file(action, "Selected records", header, rows, kinds, f"{len(recs)} records",
                                  _company(db), "selected_records")
    else:
        abort(400)
    return redirect(back)


# ---------------------------------------------------------------- exports of a whole list
@bp.route("/records/export")
@login_required
def export_list():
    db = get_db()
    fmt = "pdf" if request.args.get("fmt") == "pdf" else "xlsx"
    tab = request.args.get("tab", "mine")
    tab = tab if tab in available_tabs(db, g.user) else "mine"
    where, params = tab_clause(db, tab, g.user)
    sq, sp = search_clause((request.args.get("q") or "").strip())
    fq, order, fp, op, _info = list_options(db, g.user, request.args)
    rows = db.execute(rec_select() + " WHERE " + where + sq + fq + " ORDER BY " + order,
                      params + sp + fp + op).fetchall()
    header, out, kinds = build_table(db, rows, any(r["owner_id"] != g.user["id"] for r in rows))
    log(db, "export", f"{fmt}: {len(rows)} records ({tab})")
    db.commit()
    return exports.table_file(fmt, "Records", header, out, kinds, f"{len(rows)} records · {g.user['full_name']}",
                              _company(db), "records_" + g.user["username"])


@bp.route("/admin/records/export")
@admin_required
def export_admin():
    db = get_db()
    fmt = "pdf" if request.args.get("fmt") == "pdf" else "xlsx"
    where, params, _q, _dept, _owner, order, op, _info = _record_filters()
    rows = db.execute(rec_select() + " WHERE " + where + " ORDER BY " + order, params + op).fetchall()
    header, out, kinds = build_table(db, rows, True)
    log(db, "export", f"{fmt}: {len(rows)} records (admin)")
    db.commit()
    return exports.table_file(fmt, "All records", header, out, kinds, f"{len(rows)} records", _company(db), "all_records")


@bp.route("/records/<int:rid>/pdf")
@login_required
def record_pdf(rid):
    """PDF of one record: ONLY the columns' values the person ticked.
    The PDF form on the record page sends pdf_form=1, so a form submitted
    with every box unticked gives an empty PDF ("No information to show"),
    not the full record. A direct link with no pdf_form marker still gives
    all columns, as before, so old links and bookmarks keep working.
    Edit history and repair log are never part of the PDF."""
    rec, _level = load_record(rid, "view")
    db = get_db()
    cols = get_columns(db, rec["department_id"])
    chosen = {int(x) for x in request.args.getlist("col") if x.isdigit()}
    if request.args.get("pdf_form"):
        cols = [c for c in cols if c["id"] in chosen]
    elif chosen:
        cols = [c for c in cols if c["id"] in chosen]
    vals = values_for(db, [rid])[rid]
    details = [[c["name"], show_when(vals[c["id"]]) if c["col_type"] == "date" else vals[c["id"]]]
               for c in cols if vals.get(c["id"])]                      # empty fields are left out
    data = exports.document_pdf(f"{rec['department_name']} record #{rid}",
                                f"Owner: {rec['owner_name']}",
                                [("", ["Field", "Value"], details or [["", "No information to show."]])], _company(db))
    from flask import Response
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="record_{rid}.pdf"'
    log(db, "export", f"pdf of record {rid}")
    db.commit()
    return resp


# ---------------------------------------------------------------- reports
def _scope(user):
    """Admins report on everything, department admins on their own department."""
    if is_portal_admin(user):
        return "1=1", []
    if user["is_dept_admin"]:
        return "r.department_id=?", [user["department_id"]]
    abort(403)


@bp.route("/reports")
@login_required
def reports():
    scope, sp = _scope(g.user)
    repairs_on = get_db().execute("SELECT COUNT(*) FROM departments d WHERE d.repairs_enabled=1 AND "
                                  + scope.replace("r.department_id", "d.id"), sp).fetchone()[0] > 0
    return render_template("reports.html", repairs_on=repairs_on)


@bp.route("/reports/<name>/<fmt>")
@login_required
def report(name, fmt):
    db = get_db()
    scope, sp = _scope(g.user)
    fmt = "pdf" if fmt == "pdf" else "xlsx"
    today = date.today()
    sheets, title = [], ""
    if name == "records":
        title = "All records"
        rows = db.execute(rec_select() + " WHERE r.deleted_at IS NULL AND " + scope + " ORDER BY d.name, u.full_name, r.id", sp).fetchall()
        header, out, kinds = build_table(db, rows, True)
        sheets = [{"title": "Records", "header": header, "rows": out, "kinds": kinds}]
    elif name == "reminders":
        title = "Reminders (passed and next 90 days)"
        found = [r for r in reminder_rows(db, g.user, "0000-01-01", (today + timedelta(days=90)).isoformat(), limit=3000)
                 if (is_portal_admin(g.user) or r["department_id"] == g.user["department_id"])]
        sums = summaries_for(db, found)
        out = []
        for r in found:
            try:
                left = (date.fromisoformat(r["reminder_date"][:10]) - today).days
            except ValueError:
                continue
            out.append([r["department_name"], sums[r["id"]], r["owner_name"], r["reminder_name"], r["reminder_date"], left])
        sheets = [{"title": "Reminders", "header": ["Department", "Record", "Owner", "Date field", "Date", "Days left"],
                   "rows": out, "kinds": ["text"] * 5 + ["number"]}]
    elif name == "repairs":
        title = "Open repairs"
        found = db.execute(rec_select(", p.date_in, p.problem, p.fixed_by, p.cost") + " JOIN repairs p ON p.record_id=r.id "
                           "JOIN departments dd ON dd.id=r.department_id AND dd.repairs_enabled=1 "
                           "WHERE p.date_back IS NULL AND r.deleted_at IS NULL AND " + scope + " ORDER BY p.date_in", sp).fetchall()
        sums = summaries_for(db, found)
        out = [[r["department_name"], sums[r["id"]], r["owner_name"], r["date_in"], r["problem"], r["fixed_by"], r["cost"]]
               for r in found]
        sheets = [{"title": "Open repairs", "header": ["Department", "Record", "Owner", "Sent on", "Problem", "Fixed by", "Cost"],
                   "rows": out, "kinds": ["text"] * 6 + ["number"]}]
    elif name == "summary":
        title = "Summary"
        by_dept = db.execute("SELECT d.name, COUNT(r.id) AS n FROM departments d LEFT JOIN records r ON r.department_id=d.id "
                             "AND r.deleted_at IS NULL WHERE " + scope.replace("r.department_id", "d.id") +
                             " GROUP BY d.id ORDER BY n DESC", sp).fetchall()
        by_status = db.execute("SELECT v.value AS label, COUNT(*) AS n FROM record_values v "
                               "JOIN columns c ON c.id=v.column_id AND c.removed_at IS NULL AND lower(c.name)='status' "
                               "JOIN records r ON r.id=v.record_id AND r.deleted_at IS NULL WHERE " + scope +
                               " GROUP BY v.value ORDER BY n DESC", sp).fetchall()
        sheets = [{"title": "By department", "header": ["Department", "Records"], "rows": [[r["name"], r["n"]] for r in by_dept],
                   "kinds": ["text", "number"]},
                  {"title": "By status", "header": ["Status", "Records"], "rows": [[r["label"], r["n"]] for r in by_status],
                   "kinds": ["text", "number"]}]
    elif name == "activity" and is_portal_admin(g.user):
        title = "Activity log (last 2000)"
        rows = db.execute("SELECT created_at, username, action, details, ip FROM activity_log ORDER BY id DESC LIMIT 2000").fetchall()
        sheets = [{"title": "Activity", "header": ["Time", "User", "Action", "Details", "IP address"],
                   "rows": [list(r) for r in rows], "kinds": ["text"] * 5}]
    else:
        abort(404)
    log(db, "report", f"{name} ({fmt})")
    db.commit()
    return exports.sheets_file(fmt, title, sheets, _company(db), "report_" + name,
                               f"{g.user['full_name']} · {today.isoformat()}")
