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
from core import (MANAGE_LEVELS, access_level, add_history, build_table, dept_member_ids, get_columns,
                  get_record, notify, rec_select, reminder_rows, search_clause, soft_delete,
                  summaries_for, values_for)
from models import get_db, log, setting_get
from routes_admin import _record_filters
from routes_records import (_load as load_record, available_tabs, label_items, list_options, tab_clause)
from utils import csv_response

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
        if not chosen:
            flash("Choose the departments to share with.", "error")
            return redirect(back)
        for rec in mine:
            for d in chosen:
                if not db.execute("SELECT 1 FROM record_shares WHERE record_id=? AND department_id=?", (rec["id"], d)).fetchone():
                    db.execute("INSERT INTO record_shares(record_id,department_id,shared_by) VALUES (?,?,?)",
                               (rec["id"], d, g.user["id"]))
                    add_history(db, rec["id"], g.user, "shared", new=names[d])
        for d in chosen:
            notify(db, dept_member_ids(db, d), f"{g.user['full_name']} shared {len(mine)} record(s) with your department.",
                   "/records?tab=shared_with_me", skip=g.user["id"])
        log(db, "bulk_share", f"{len(mine)} records")
        db.commit()
        flash(f"{len(mine)} record(s) shared. Records you do not own were skipped.", "ok")
    elif action == "delete":
        for rec in mine:
            soft_delete(db, g.user, rec)
        log(db, "bulk_delete", f"{len(mine)} records")
        db.commit()
        flash(f"{len(mine)} record(s) moved to the recycle bin.", "ok")
    elif action == "labels":
        return render_template("qr_label.html", items=label_items(db, recs), many=True)
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
    rec, _level = load_record(rid, "view")
    db = get_db()
    cols = get_columns(db, rec["department_id"])
    vals = values_for(db, [rid])[rid]
    details = [[c["name"], vals.get(c["id"]) or ""] for c in cols]
    repairs = [[r["date_in"], r["problem"], r["fixed_by"], r["cost"], r["date_back"] or "In repair"]
               for r in db.execute("SELECT * FROM repairs WHERE record_id=? ORDER BY id DESC", (rid,))]
    history = [[h["at"], h["full_name"] or "", h["action"] + (": " + h["field"] if h["field"] else ""),
                f"{h['old_value'] or ''} -> {h['new_value'] or ''}" if h["field"] else (h["new_value"] or "")]
               for h in db.execute("SELECT * FROM record_history WHERE record_id=? ORDER BY id DESC LIMIT 60", (rid,))]
    data = exports.document_pdf(f"{rec['department_name']} record #{rid}",
                                f"Owner: {rec['owner_name']} · {rec['updated_at']}",
                                [("Details", ["Field", "Value"], details),
                                 ("Repair log", ["Sent", "Problem", "Fixed by", "Cost", "Back"], repairs),
                                 ("Edit history", ["When", "Who", "What", "Change"], history)], _company(db))
    from flask import Response
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="record_{rid}.pdf"'
    log(db, "export", f"pdf of record {rid}")
    db.commit()
    return resp


# ---------------------------------------------------------------- reports
def _scope(user):
    """Admins report on everything, department admins on their own department."""
    if user["role"] == "admin":
        return "1=1", []
    if user["is_dept_admin"]:
        return "r.department_id=?", [user["department_id"]]
    abort(403)


@bp.route("/reports")
@login_required
def reports():
    _scope(g.user)
    return render_template("reports.html")


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
                 if (g.user["role"] == "admin" or r["department_id"] == g.user["department_id"])]
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
    elif name == "activity" and g.user["role"] == "admin":
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


# ---------------------------------------------------------------- saved views (filters and sorting)
VIEW_PAGES = {"records": "records.list_records", "admin_records": "admin.all_records"}
VIEW_KEYS = ("tab", "q", "sort", "dir", "fcol", "fval", "department", "owner")


@bp.route("/views/save", methods=["POST"])
@login_required
def view_save():
    page = request.form.get("page", "")
    name = (request.form.get("name") or "").strip()[:60]
    if page not in VIEW_PAGES or not name or (page == "admin_records" and g.user["role"] != "admin"):
        flash("Give the view a name.", "error")
        return redirect(_safe_back(request.form.get("back")))
    query = urlencode([(k, v) for k, v in parse_qsl(request.form.get("query", "")) if k in VIEW_KEYS and v])
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM saved_views WHERE user_id=? AND page=?", (g.user["id"], page)).fetchone()[0] >= 20:
        flash("You can save up to 20 views. Delete one first.", "error")
    else:
        db.execute("INSERT INTO saved_views(user_id,page,name,query) VALUES (?,?,?,?)", (g.user["id"], page, name, query))
        db.commit()
        flash("View saved.", "ok")
    return redirect(url_for(VIEW_PAGES[page]) + ("?" + query if query else ""))


@bp.route("/views/<int:vid>/delete", methods=["POST"])
@login_required
def view_delete(vid):
    db = get_db()
    row = db.execute("SELECT * FROM saved_views WHERE id=? AND user_id=?", (vid, g.user["id"])).fetchone()
    if row is None:
        abort(404)
    db.execute("DELETE FROM saved_views WHERE id=?", (vid,))
    db.commit()
    flash("View deleted.", "ok")
    return redirect(url_for(VIEW_PAGES.get(row["page"], "records.list_records")))
