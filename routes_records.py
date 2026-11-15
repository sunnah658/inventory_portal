"""
routes_records.py - pages every user sees: records, detail, sharing, repair log,
attachments, recycle bin and reminders.

Used by: app.py (registers it).   Uses: auth.py, core.py, models.py, utils.py, config.py
Templates: records_list, record_form, record_detail, bin, reminders.

Permission levels (see core.access_level):
  owner      - made the record: edit, share, delete, hand over, public QR
  shared     - member of a department it is shared with: view and edit every field
  admin      - everything
  supervisor - department admin of the record's department: view and comment/suggest only
  viewer     - allowed to view another department: view and comment/suggest only
"""
import json
import os
import secrets
import uuid
from datetime import date, datetime, timedelta

import segno
from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   send_file, url_for)

import config
from auth import admin_required, login_required
from backup import make_backup
from utils import is_portal_admin, is_true_admin
import scanner
from core import (ddb_attachment_info, ddb_can_add, ddb_columns, ddb_history, ddb_is_tab_admin, ddb_tabs, ddb_values, change_owner, may_change_owner, owner_candidates, display_code, display_record_value, external_url, first_text_value, EDIT_LEVELS, MANAGE_LEVELS, PERMISSIONS, PERM_WORDS, clean_permission, share_with_department,
                  share_with_user, access_level, add_history, admin_ids, build_csv, can_use_record_attachments,
                  column_names, col_weight, create_record, dept_member_ids, filter_clause, get_record,
                  hidden_mine_columns, set_hidden_mine_columns, record_columns,
                  names_for_records, notify, notify_admin_task, parse_code_text, parse_form, print_col_widths, purge_application, purge_ddb_row, purge_invoice, purge_record, purge_request, purge_user_account, rec_select, reminder_rows,
                  restore, search_clause, soft_delete, sort_clause, summaries_for, table_context, USER_COLUMN_TYPES,
                  update_record, values_for, viewable_departments, USER_TYPE_LABEL)
from models import get_db, log
from utils import csv_response, is_portal_admin, like_pattern, page_info

bp = Blueprint("records", __name__)
TABS = ("mine", "shared_by_me", "shared_with_me", "department", "viewing")


def available_tabs(db, user):
    """Tabs this user can use (department / viewing only appear when allowed)."""
    tabs = ["mine", "shared_by_me", "shared_with_me"]
    if user["department_id"]:
        # "My department" is on every user's My records page (2026-11-05):
        # it lists that user's own rows in the Department Database, not
        # personal records - see _department_tab_view.
        tabs.append("department")
    if viewable_departments(db, user):
        tabs.append("viewing")
    return tabs


def tab_clause(db, tab, user):
    """SQL for the list tabs."""
    if tab == "shared_with_me":
        return ("r.deleted_at IS NULL AND r.owner_id != ? AND (EXISTS (SELECT 1 FROM record_shares s "
                "WHERE s.record_id=r.id AND s.department_id=?) OR EXISTS (SELECT 1 FROM record_user_shares us "
                "WHERE us.record_id=r.id AND us.user_id=?))", [user["id"], user["department_id"], user["id"]])
    if tab == "shared_by_me":
        return ("r.deleted_at IS NULL AND r.owner_id=? AND (EXISTS (SELECT 1 FROM record_shares s "
                "WHERE s.record_id=r.id) OR EXISTS (SELECT 1 FROM record_user_shares us "
                "WHERE us.record_id=r.id))", [user["id"]])
    # The "department" tab is no longer personal records (2026-11-05): it
    # lists the user's own Department Database rows, handled by
    # _department_tab_view. Any caller that still passes "department" here
    # (for example a bulk export link) falls through to the user's own
    # records only, never the whole department.
    if tab == "viewing":
        granted = viewable_departments(db, user)
        if granted:
            return ("r.deleted_at IS NULL AND r.department_id IN (%s)" % ",".join("?" * len(granted)), granted)
        return "0", []
    return "r.deleted_at IS NULL AND r.owner_id=?", [user["id"]]


def list_options(db, user, args):
    """Sorting and filter choices from the URL. Returns (extra SQL, ORDER BY, params, info)."""
    sort = args.get("sort", "updated")
    direction = "asc" if args.get("dir") == "asc" else "desc"
    fcol = (args.get("fcol") or "").strip()
    fval = (args.get("fval") or "").strip()
    fq, fp = filter_clause(fcol, fval)
    order, op = sort_clause(db, sort, direction)
    return fq, order, fp, op, {"sort": sort, "dir": direction, "fcol": fcol, "fval": fval}


# ---------------------------------------------------------------- "My department" tab
# (2026-11-05) The "My department" tab on the My records page is on every
# user's page and lists that user's own work in the Department Database,
# grouped under the tab each item belongs to: their own ddb_rows in their
# own department, across the department's tabs, plus — since build 62 —
# their own invoices and item requests, and the invoices and requests
# sent to them as an approval step. Nothing here can be edited: a
# Department Database row has a Locate button that opens the Department
# Database page on the row's own tab, scrolled to and highlighting that
# exact row; an invoice or a request opens on its own page, because the
# Department Database lists for those are filtered to whoever is
# looking, so a page link would land on the wrong person's list in the
# admin's view of a user's records.
def _department_docs(db, user, q=None):
    """The user's invoices and item requests for the My department tab,
    as four lists: (own invoices, invoices sent to them, own requests,
    requests sent to them). The definitions mirror the Department
    Database Invoices / Request items tabs: own = created by them in
    their own department; sent = any approval step with their user id,
    any department. Deleted items live in the Recycle Bin and are
    excluded. q searches the same fields the Department Database search
    does (invoice: customer, number, share code; request: owner,
    recipient, kind, number, share code, department)."""
    like3 = [like_pattern(q)] * 3 if q else []
    inv_search = (" AND (i.customer_name LIKE ? ESCAPE '\\' OR i.number LIKE ? ESCAPE '\\' "
                  "OR i.public_code LIKE ? ESCAPE '\\')") if q else ""
    inv_base = ("SELECT i.*, t.name AS template_name, u.full_name AS owner_name, d.name AS dept_name "
                "FROM invoices i LEFT JOIN invoice_templates t ON t.id=i.template_id "
                "LEFT JOIN users u ON u.id=i.owner_id LEFT JOIN departments d ON d.id=i.department_id ")
    own_inv = db.execute(inv_base + "WHERE i.deleted_at IS NULL AND i.department_id=? AND i.owner_id=?"
                          + inv_search + " ORDER BY i.id DESC",
                         [user["department_id"], user["id"]] + like3).fetchall()
    sent_inv = db.execute(inv_base + "WHERE i.deleted_at IS NULL AND EXISTS "
                          "(SELECT 1 FROM invoice_steps s WHERE s.invoice_id=i.id AND s.user_id=?)"
                          + inv_search + " ORDER BY i.id DESC",
                          [user["id"]] + like3).fetchall()
    like6 = [like_pattern(q)] * 6 if q else []
    req_search = (" AND (u.full_name LIKE ? ESCAPE '\\' OR ru.full_name LIKE ? ESCAPE '\\' "
                  "OR k.name LIKE ? ESCAPE '\\' OR r.number LIKE ? ESCAPE '\\' "
                  "OR r.public_code LIKE ? ESCAPE '\\' OR d.name LIKE ? ESCAPE '\\')") if q else ""
    req_base = ("SELECT r.*, k.name AS kind_name, u.full_name AS owner_name, ru.full_name AS recipient_name, "
                "d.name AS dept_name FROM item_requests r "
                "LEFT JOIN item_request_kinds k ON k.id=r.kind_id "
                "LEFT JOIN users u ON u.id=r.owner_id LEFT JOIN users ru ON ru.id=r.recipient_id "
                "LEFT JOIN departments d ON d.id=r.department_id ")
    own_req = db.execute(req_base + "WHERE r.deleted_at IS NULL AND r.department_id=? AND r.owner_id=?"
                         + req_search + " ORDER BY r.id DESC",
                         [user["department_id"], user["id"]] + like6).fetchall()
    sent_req = db.execute(req_base + "WHERE r.deleted_at IS NULL AND EXISTS "
                          "(SELECT 1 FROM item_request_steps s WHERE s.request_id=r.id AND s.user_id=?)"
                          + req_search + " ORDER BY r.id DESC",
                          [user["id"]] + like6).fetchall()
    return own_inv, sent_inv, own_req, sent_req


def _department_row_count(db, user):
    """How many of the user's own Department Database items exist: their
    own rows plus their own invoices and requests and the ones sent to
    them (build 62). This is the My department pill count; the tab
    itself also filters by search."""
    if not user["department_id"]:
        return 0
    n = db.execute(
        "SELECT COUNT(*) FROM ddb_rows r JOIN ddb_tabs t ON t.id=r.tab_id "
        "WHERE r.department_id=? AND r.owner_id=? AND r.deleted_at IS NULL AND t.removed_at IS NULL",
        (user["department_id"], user["id"])).fetchone()[0]
    own_inv, sent_inv, own_req, sent_req = _department_docs(db, user)
    return n + len(own_inv) + len(sent_inv) + len(own_req) + len(sent_req)


def _department_rows_where(user, q):
    """WHERE clause (and params) for the user's own Department Database rows."""
    where = ["r.department_id=?", "r.owner_id=?", "r.deleted_at IS NULL",
             "EXISTS (SELECT 1 FROM ddb_tabs t WHERE t.id=r.tab_id AND t.removed_at IS NULL)"]
    params = [user["department_id"], user["id"]]
    if q:
        where.append("EXISTS (SELECT 1 FROM ddb_values v WHERE v.row_id=r.id AND v.value LIKE ? ESCAPE '\\')")
        params.append(like_pattern(q))
    return " AND ".join(where), params


def _ddb_display_map(db, rows, cols):
    """{row_id: {column_id: shown value}} plus attachment download links,
    the same display the Department Database page itself uses."""
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


def _locate_pages(db, rows):
    """For each row, the page it sits on in its own Department Database tab
    under that page's default sort (updated_at DESC, id DESC), so a Locate
    link opens the exact page the row is on. {row_id: page}."""
    pages = {}
    for tab_id in {r["tab_id"] for r in rows}:
        ids = [x[0] for x in db.execute(
            "SELECT id FROM ddb_rows WHERE tab_id=? AND deleted_at IS NULL "
            "ORDER BY updated_at DESC, id DESC", (tab_id,))]
        for i, rid in enumerate(ids):
            pages[rid] = i // config.PER_PAGE + 1
    return pages


def _department_tab_view(db, user, tabs, counts, q, args, admin_view=False,
                         list_endpoint="records.list_records", list_args=None):
    dept_id = user["department_id"]
    where, params = _department_rows_where(user, q)
    ddb_total = db.execute("SELECT COUNT(*) FROM ddb_rows r WHERE " + where, params).fetchone()[0]
    page, pages, offset = page_info(ddb_total, args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute(
        "SELECT r.*, t.name AS tab_name, t.position AS tab_pos FROM ddb_rows r "
        "JOIN ddb_tabs t ON t.id=r.tab_id WHERE " + where +
        " ORDER BY t.position, t.id, r.updated_at DESC, r.id DESC LIMIT ? OFFSET ?",
        params + [config.PER_PAGE, offset]).fetchall()
    groups, by_tab = [], {}
    for r in rows:
        if r["tab_id"] not in by_tab:
            by_tab[r["tab_id"]] = {"tab_id": r["tab_id"], "tab_name": r["tab_name"], "kind": "ddb",
                                   "cols": ddb_columns(db, dept_id, tab_id=r["tab_id"]), "rows": []}
            groups.append(by_tab[r["tab_id"]])
        by_tab[r["tab_id"]]["rows"].append(r)
    for g in groups:
        g["vmap"], g["urls"] = _ddb_display_map(db, g["rows"], g["cols"])
        # Print widths for this tab's columns (no trailing column here: the
        # rows are the user's own, so there is no Added by column).
        g["widths"] = print_col_widths([col_weight(c["col_type"]) for c in g["cols"]])
    # Invoices and item requests (build 62): the user's own, and the ones
    # sent to them as an approval step — the Department Database page's
    # Invoices and Request items tabs, as groups on this tab. They are not
    # paged with the rows (a user has only a handful of each); the pager
    # still pages the Department Database rows alone.
    own_inv, sent_inv, own_req, sent_req = _department_docs(db, user, q or None)
    for tab_name, kind, items in (("Invoices", "invoices", own_inv),
                                  ("Invoices sent to you", "invoices", sent_inv),
                                  ("Request items", "requests", own_req),
                                  ("Item requests sent to you", "requests", sent_req)):
        if items:
            groups.append({"tab_name": tab_name, "kind": kind, "rows": items})
    total = ddb_total + len(own_inv) + len(sent_inv) + len(own_req) + len(sent_req)
    keep = {k: v for k, v in args.items() if k != "page"}
    return render_template("records_department.html", tabs=tabs, tab="department",
                           counts=counts, q=q, groups=groups, total=total,
                           page=page, pages=pages, keep=keep, dept_id=dept_id,
                           admin_view=admin_view, view_user=user,
                           list_endpoint=list_endpoint, list_args=list_args or {},
                           bar_hidden=dict(list_args or {}, tab="department"),
                           locate_pages=_locate_pages(db, rows))


def _download_department_csv(db, user, q):
    """CSV of the user's own Department Database rows (the "My department" tab)."""
    where, params = _department_rows_where(user, q)
    rows = db.execute(
        "SELECT r.*, t.name AS tab_name, t.position AS tab_pos FROM ddb_rows r "
        "JOIN ddb_tabs t ON t.id=r.tab_id WHERE " + where +
        " ORDER BY t.position, t.id, r.updated_at DESC, r.id DESC", params).fetchall()
    # A selection (ids=1,2,3) downloads only those rows; without it, all of
    # the user's rows are downloaded, as before.
    ids = request.args.get("ids")
    if ids:
        idset = {x for x in ids.split(",") if x.isdigit()}
        rows = [r for r in rows if str(r["id"]) in idset]
    cols, seen = [], set()
    for r in rows:
        for c in ddb_columns(db, user["department_id"], tab_id=r["tab_id"]):
            if c["name"] not in seen:
                seen.add(c["name"])
                cols.append(c["name"])
    vmap = ddb_values(db, [r["id"] for r in rows])
    out = []
    for r in rows:
        # Values live under this row's own tab's column ids (two tabs may
        # share a column name with different ids).
        by_name = {c["name"]: vmap[r["id"]].get(c["id"], "") or ""
                   for c in ddb_columns(db, user["department_id"], tab_id=r["tab_id"])}
        out.append([r["tab_name"]] + [by_name.get(name, "") for name in cols])
    log(db, "download_csv", f"{len(rows)} department database rows (mine)")
    db.commit()
    return csv_response(["Department DB tab"] + cols, out, "my_department_rows_" + user["username"])


def _load(rid, need="view"):
    """Load a record and check permission. need = view | edit | manage."""
    db = get_db()
    rec = get_record(db, rid)
    if rec is None:
        abort(404)
    level = access_level(db, g.user, rec)
    if level is None:
        abort(404)                                  # do not reveal that it exists
    if rec["deleted_at"] and level not in MANAGE_LEVELS:
        abort(404)
    if rec["deleted_at"] and need == "edit":
        abort(404)
    if need == "manage" and level not in MANAGE_LEVELS:
        abort(403)
    if need == "edit" and level not in EDIT_LEVELS:
        abort(403)
    return rec, level


def code_redirect(text):
    """If the search text is a QR code such as 'HRC-48392', the page of that code (else None).

    Only the random 5-digit code redirects; old sequential numbers do not,
    so they are treated as ordinary search text instead of opening a link."""
    wanted = parse_code_text(text)
    if wanted is None:
        return None
    return redirect(url_for("public.code_page", code=wanted))


# ---------------------------------------------------------------- lists
@bp.route("/")
@login_required
def home():
    if is_portal_admin(g.user):
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("records.list_records"))


def _mine_column_picker(db, user):
    """The columns offered on this user's Mine tab, grouped by department:
    the user's own department plus every department their records sit in.
    Each group lists the user's own columns for that department (build 64:
    the department's columns are no longer shown on a user's personal
    records). Returns [(dept_id, dept_name, [columns])]. Each column is a
    dict; it also carries 'shown' (its picker tick) and 'used' (how many
    of their live records have a value in it), the two extra columns the
    admin's columns page shows (build 62)."""
    dept_ids = [user["department_id"]] if user["department_id"] else []
    for (d,) in db.execute("SELECT DISTINCT department_id FROM records WHERE owner_id=? AND deleted_at IS NULL",
                           (user["id"],)):
        if d not in dept_ids:
            dept_ids.append(d)
    hidden = hidden_mine_columns(db, user["id"])
    out = []
    for did in dept_ids:
        row = db.execute("SELECT name FROM departments WHERE id=?", (did,)).fetchone()
        cols = []
        for c in record_columns(db, did, user["id"]):
            c = dict(c)
            c["shown"] = c["id"] not in hidden
            c["used"] = db.execute(
                "SELECT COUNT(*) FROM record_values v JOIN records r ON r.id=v.record_id "
                "WHERE v.column_id=? AND r.owner_id=? AND r.deleted_at IS NULL "
                "AND v.value IS NOT NULL AND v.value != ''",
                (c["id"], user["id"])).fetchone()[0]
            cols.append(c)
        if cols:
            out.append((did, row["name"] if row else "", cols))
    return out


def _own_column(db, cid, user):
    """One of this user's own columns, or 404 (a department column, another
    user's column, a removed column and a missing one all look the same)."""
    col = db.execute("SELECT * FROM columns WHERE id=? AND user_id=? AND removed_at IS NULL",
                     (cid, user["id"])).fetchone()
    if col is None:
        abort(404)
    return col


def _own_removed_column(db, cid, user):
    """One of this user's own columns that was removed, or 404 (a live
    column, a department column, another user's column and a missing one
    all look the same)."""
    col = db.execute("SELECT * FROM columns WHERE id=? AND user_id=? AND removed_at IS NOT NULL",
                     (cid, user["id"])).fetchone()
    if col is None:
        abort(404)
    return col


def _my_columns_groups(db, user):
    """All of this user's own columns (any department), grouped by
    department like the Mine-tab picker does. Each column carries
    'shown' (its picker tick) and 'used' (how many of the user's live
    records have a value in it) — the two extra columns the admin's
    columns page shows (build 62)."""
    hidden = hidden_mine_columns(db, user["id"])
    groups = []
    for (did,) in db.execute("SELECT DISTINCT department_id FROM columns "
                             "WHERE user_id=? AND removed_at IS NULL ORDER BY department_id",
                             (user["id"],)):
        row = db.execute("SELECT name FROM departments WHERE id=?", (did,)).fetchone()
        cols = []
        for c in db.execute("SELECT * FROM columns WHERE department_id=? AND user_id=? "
                            "AND removed_at IS NULL ORDER BY position, id", (did, user["id"])):
            c = dict(c)
            c["shown"] = c["id"] not in hidden
            c["used"] = db.execute(
                "SELECT COUNT(*) FROM record_values v JOIN records r ON r.id=v.record_id "
                "WHERE v.column_id=? AND r.owner_id=? AND r.deleted_at IS NULL "
                "AND v.value IS NOT NULL AND v.value != ''",
                (c["id"], user["id"])).fetchone()[0]
            cols.append(c)
        groups.append((did, row["name"] if row else "", cols))
    return groups


def _user_column_name_taken(db, dept_id, user_id, name, exclude=None):
    """Does this department already have a column with this name — a
    department column, or one of this user's own columns in it? (Two
    different users may each have a column of the same name; the unique
    index only stops the same user, or the department, from doubling it.)"""
    row = db.execute("SELECT id FROM columns WHERE department_id=? AND removed_at IS NULL "
                     "AND user_id IS NULL AND lower(name)=lower(?)", (dept_id, name)).fetchone()
    if row:
        return True
    row = db.execute("SELECT id FROM columns WHERE department_id=? AND user_id=? AND removed_at IS NULL "
                     "AND lower(name)=lower(?)", (dept_id, user_id, name)).fetchone()
    return row is not None and (exclude is None or row["id"] != exclude)


def _parse_column_options(text):
    return "\n".join(o.strip() for o in (text or "").replace("\r", "").split("\n") if o.strip())


def _display_values(cols, values):
    """Values as shown on a form or a detail page: an attachment column
    shows the file's name, not the stored JSON."""
    return {c["id"]: display_record_value(c, values.get(c["id"])) for c in cols}


def _list_records_view(db, user, args, admin_view=False):
    """The My records page of one user. admin_view=True renders it for a
    portal admin / administrative permission user looking at that user's
    page (build 60): view and delete only, no Add, Edit, Export or Print.
    The Mine tab shows the page owner's own column choice, not the
    viewer's."""
    tabs = available_tabs(db, user)
    tab = args.get("tab", "mine")
    tab = tab if tab in tabs else "mine"
    q = (args.get("q") or "").strip()
    counts = {}
    for t in tabs:
        if t == "department":
            counts[t] = _department_row_count(db, user)
        else:
            where, params = tab_clause(db, t, user)
            counts[t] = db.execute("SELECT COUNT(*) FROM records r WHERE " + where, params).fetchone()[0]
    list_endpoint = "admin.user_records" if admin_view else "records.list_records"
    list_args = {"user": user["id"]} if admin_view else {}
    if tab == "department":
        # "My department" lists the user's own Department Database rows, not
        # personal records (2026-11-05). Nothing can be edited from it.
        return _department_tab_view(db, user, tabs, counts, q, args,
                                    admin_view=admin_view, list_endpoint=list_endpoint,
                                    list_args=list_args)
    where, params = tab_clause(db, tab, user)
    sq, sp = search_clause(q)
    fq, order, fp, op, info = list_options(db, user, args)
    total = db.execute("SELECT COUNT(*) FROM records r WHERE " + where + sq + fq, params + sp + fp).fetchone()[0]
    page, pages, offset = page_info(total, args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute(rec_select() + " WHERE " + where + sq + fq + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                      params + sp + fp + op + [config.PER_PAGE, offset]).fetchall()
    keep = {k: v for k, v in args.items() if k != "page"}
    hidden = hidden_mine_columns(db, user["id"]) if tab == "mine" else None
    picker = _mine_column_picker(db, user) if tab == "mine" and not admin_view else []
    # The Mine tab and Shared by me list only this user's own records, so
    # their own columns belong there too (build 61); every other tab shows
    # department columns alone. The admin view uses the page owner's
    # columns, not the viewer's.
    mine_user_id = user["id"] if tab in ("mine", "shared_by_me") else None
    can_attach = can_use_record_attachments(g.user)
    return render_template("records_list.html", ctx=table_context(db, rows, user, hidden=hidden,
                                                                  mine_user_id=mine_user_id),
                           tab=tab, tabs=tabs, q=q, counts=counts, total=total,
                           page=page, pages=pages, info=info, names=column_names(db, user),
                           keep=keep, admin_view=admin_view, view_user=user,
                           list_endpoint=list_endpoint, list_args=list_args,
                           bar_hidden=dict(list_args, tab=tab),
                           admin_next=url_for(list_endpoint, tab=tab, **list_args) if admin_view else "",
                           picker=picker, hidden=hidden or set(),
                           can_attach=can_attach,
                           col_types=[t for t in USER_COLUMN_TYPES if t[0] != "attachment" or can_attach],
                           type_label=USER_TYPE_LABEL,
                           departments=[] if admin_view else db.execute("SELECT id, name FROM departments ORDER BY name").fetchall())


@bp.route("/records")
@login_required
def list_records():
    db = get_db()
    code_page = code_redirect(request.args.get("q"))          # typing HRC-12 opens that QR code
    if code_page:
        return code_page
    return _list_records_view(db, g.user, request.args)


@bp.route("/records/columns", methods=["POST"])
@login_required
def save_mine_columns():
    """Save this user's own Mine-tab column choice (build 60): tick a
    column to show it on the Mine tab, untick to hide it. The choice is
    personal — it changes nobody else's page — and the department admin
    still makes the department's columns themselves."""
    db = get_db()
    picker = _mine_column_picker(db, g.user)
    offered = [c["id"] for _d, _n, cols in picker for c in cols]
    shown = {int(v[4:]) for v in request.form.getlist("col")
             if v.startswith("col_") and v[4:].isdigit()}
    hidden = {cid for cid in offered if cid not in shown}
    set_hidden_mine_columns(db, g.user["id"], offered, hidden)
    db.commit()
    flash("Your Mine tab columns are saved.", "ok")
    return redirect(url_for("records.list_records", tab="mine"))


# ---------------------------------------------------------------- my columns page (build 63)
@bp.route("/records/my-columns")
@login_required
def my_columns():
    """Manage columns: this user's own columns on a page of their own, laid
    out like the portal admin's Departments -> record columns page:
    KPI cards on top, the table on the left, the Add column card in the
    right rail. The Mine tab's Columns box keeps only the tick-box
    picker, with a link here."""
    db = get_db()
    groups = _my_columns_groups(db, g.user)
    removed = db.execute("SELECT COUNT(*) FROM columns WHERE user_id=? AND removed_at IS NOT NULL",
                         (g.user["id"],)).fetchone()[0]
    total = sum(len(cols) for _did, _dname, cols in groups)
    protected = sum(1 for _did, _dname, cols in groups for c in cols if c["protected"])
    can_attach = can_use_record_attachments(g.user)
    return render_template("records_my_columns.html",
                           groups=groups, removed=removed, total=total, protected=protected,
                           col_types=[t for t in USER_COLUMN_TYPES if t[0] != "attachment" or can_attach],
                           can_attach=can_attach, type_label=USER_TYPE_LABEL)


@bp.route("/records/columns/removed")
@login_required
def removed_mine_columns():
    """My removed columns, like the admin's Removed columns page: hidden
    but their data is kept — restore one, or erase it for good."""
    db = get_db()
    cols = db.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM record_values v WHERE v.column_id=c.id) AS used "
        "FROM columns c WHERE c.user_id=? AND c.removed_at IS NOT NULL ORDER BY c.removed_at DESC",
        (g.user["id"],)).fetchall()
    return render_template("records_removed_columns.html", cols=[dict(c) for c in cols],
                           type_label=USER_TYPE_LABEL)


# ---------------------------------------------------------------- my own columns (build 61)
# A user adds columns to their OWN Mine tab, inside the Columns box:
# name, type, dropdown options, required — the same fields the portal
# admin fills in Departments → record columns, minus reminder/time (those
# stay admin columns). The column shows only on that user's Mine tab
# (and in the admin's Users' records view of them), never on anyone
# else's page, and it is never a department column. A column can be
# protected from accidental delete (build 63): a protected column shows
# a lock and has no Remove button until its protection is removed.
@bp.route("/records/columns/add", methods=["POST"])
@login_required
def add_mine_column():
    db = get_db()
    dept = g.user["department_id"]
    if not dept:
        flash("You have no department yet, so you cannot add a column.", "error")
        return redirect(url_for("records.my_columns"))
    name = " ".join((request.form.get("name") or "").split())[:60]
    ctype = request.form.get("col_type", "")
    options = _parse_column_options(request.form.get("options"))
    can_attach = can_use_record_attachments(g.user)
    allowed = [k for k, _label in USER_COLUMN_TYPES if k != "attachment" or can_attach]
    error = None
    if not name:
        error = "Type a column name."
    elif ctype not in allowed:
        error = ("Choose a column type." if ctype != "attachment"
                 else "Only users given attachment access can add an Attachment column.")
    elif ctype == "dropdown" and not options:
        error = "A dropdown column needs at least one option (one per line)."
    elif _user_column_name_taken(db, dept, g.user["id"], name):
        error = f"There is already a column named '{name}'."
    if error:
        flash(error, "error")
        return redirect(url_for("records.my_columns"))
    pos = db.execute("SELECT COALESCE(MAX(position),-1)+1 FROM columns "
                     "WHERE department_id=? AND user_id=? AND removed_at IS NULL",
                     (dept, g.user["id"])).fetchone()[0]
    try:
        db.execute("INSERT INTO columns(department_id,user_id,name,col_type,options,required,protected,position) "
                   "VALUES (?,?,?,?,?,?,?,?)",
                   (dept, g.user["id"], name, ctype, options or None,
                    1 if request.form.get("required") else 0,
                    1 if request.form.get("protected") else 0, pos))
        log(db, "user_column_add", f"user {g.user['id']}: {name}")
        db.commit()
        flash(f"Column '{name}' added to your Mine tab.", "ok")
    except Exception:
        db.rollback()
        flash(f"There is already a column named '{name}'.", "error")
    return redirect(url_for("records.my_columns"))


@bp.route("/records/columns/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def edit_mine_column(cid):
    """Edit one of my own columns on its own page, like the admin's Edit
    column page (build 63): the name box shows the column's name —
    delete it and type a new one to rename — plus the dropdown options,
    the Required tick, the Shown tick and the Protect tick. The type
    never changes, and nobody else's column — department or another
    user's — can be touched here. Protection can be switched ON here;
    switching it OFF needs the separate "Remove protection" button, so
    it cannot happen by accident. Shown is the picker's tick: unticking
    it hides the column on the Mine tab without removing it."""
    db = get_db()
    col = _own_column(db, cid, g.user)
    if request.method == "POST":
        name = " ".join((request.form.get("name") or "").split())[:60]
        options = _parse_column_options(request.form.get("options")) if col["col_type"] == "dropdown" else None
        # Protection can be switched ON here. Switching it OFF needs the
        # separate "Remove protection" button, so it cannot happen by accident.
        protected = 1 if (col["protected"] or request.form.get("protected")) else 0
        if not name:
            flash("Type a column name.", "error")
        elif col["col_type"] == "dropdown" and not options:
            flash("A dropdown column needs at least one option.", "error")
        elif _user_column_name_taken(db, col["department_id"], g.user["id"], name, exclude=cid):
            flash(f"There is already a column named '{name}'.", "error")
        else:
            db.execute("UPDATE columns SET name=?, options=?, required=?, protected=? WHERE id=?",
                       (name, options, 1 if request.form.get("required") else 0, protected, cid))
            if request.form.get("has_shown"):
                if request.form.get("shown"):
                    db.execute("DELETE FROM user_hidden_columns WHERE user_id=? AND column_id=?",
                               (g.user["id"], cid))
                else:
                    db.execute("INSERT OR IGNORE INTO user_hidden_columns(user_id, column_id) VALUES (?, ?)",
                               (g.user["id"], cid))
            log(db, "user_column_edit", f"user {g.user['id']}: {col['name']} -> {name}")
            db.commit()
            flash("Column saved.", "ok")
            return redirect(url_for("records.my_columns"))
    dept = db.execute("SELECT * FROM departments WHERE id=?", (col["department_id"],)).fetchone()
    shown = cid not in hidden_mine_columns(db, g.user["id"])
    return render_template("records_column_edit.html", col=col, dept=dept, shown=shown,
                           type_label=USER_TYPE_LABEL)


@bp.route("/records/columns/<int:cid>/move", methods=["POST"])
@login_required
def move_mine_column(cid):
    """Move one of my own columns up or down among my own columns."""
    db = get_db()
    col = _own_column(db, cid, g.user)
    ids = [r["id"] for r in db.execute("SELECT id FROM columns WHERE department_id=? AND user_id=? "
                                       "AND removed_at IS NULL ORDER BY position, id",
                                       (col["department_id"], g.user["id"]))]
    i = ids.index(cid)
    j = i - 1 if request.form.get("dir") == "up" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
        for pos, one in enumerate(ids):
            db.execute("UPDATE columns SET position=? WHERE id=?", (pos, one))
        db.commit()
    return redirect(url_for("records.my_columns"))


@bp.route("/records/columns/<int:cid>/unprotect", methods=["POST"])
@login_required
def unprotect_mine_column(cid):
    """Remove accidental-delete protection from one of my own columns, so
    it can be removed again (build 63). Like the admin's Remove
    protection, but no password — it is the user's own column."""
    db = get_db()
    col = _own_column(db, cid, g.user)
    db.execute("UPDATE columns SET protected=0 WHERE id=?", (cid,))
    log(db, "user_column_unprotect", f"user {g.user['id']}: {col['name']}")
    db.commit()
    flash(f"Protection removed from '{col['name']}'. It can be removed now.", "ok")
    return redirect(url_for("records.my_columns"))


@bp.route("/records/columns/<int:cid>/remove", methods=["POST"])
@login_required
def remove_mine_column(cid):
    """Hide one of my own columns. Its values stay in the database, and
    it can be restored from the Removed columns page (build 63). Like
    the admin's Remove, the column name must be typed to confirm — but
    no password, because it is the user's own column. A protected
    column cannot be removed until its protection is removed."""
    db = get_db()
    col = _own_column(db, cid, g.user)
    if col["protected"]:
        flash(f"'{col['name']}' is protected. Remove the protection first.", "error")
    elif (request.form.get("confirm_name") or "").strip().lower() != col["name"].lower():
        flash("The name you typed does not match, so nothing was removed.", "error")
    else:
        db.execute("UPDATE columns SET removed_at=datetime('now','localtime') WHERE id=?", (cid,))
        log(db, "user_column_remove", f"user {g.user['id']}: {col['name']}")
        db.commit()
        flash(f"Column '{col['name']}' removed. Its data is kept; you can restore it any time.", "ok")
    return redirect(url_for("records.my_columns"))


@bp.route("/records/columns/<int:cid>/restore", methods=["POST"])
@login_required
def restore_mine_column(cid):
    """Bring a removed column of mine back with all its data (build 63),
    like the admin's Restore with data."""
    db = get_db()
    col = _own_removed_column(db, cid, g.user)
    if _user_column_name_taken(db, col["department_id"], g.user["id"], col["name"]):
        flash(f"Cannot restore: you already have a column named '{col['name']}'. "
              "Rename that one first.", "error")
    else:
        db.execute("UPDATE columns SET removed_at=NULL WHERE id=?", (cid,))
        log(db, "user_column_restore", f"user {g.user['id']}: {col['name']}")
        db.commit()
        flash(f"Column '{col['name']}' is back with all its data.", "ok")
    return redirect(url_for("records.removed_mine_columns"))


@bp.route("/records/columns/<int:cid>/erase", methods=["POST"])
@login_required
def erase_mine_column(cid):
    """Erase a removed column of mine and its data for good (build 63),
    like the admin's Erase: an automatic backup is made first, and the
    column name must be typed to confirm. No password — it is the
    user's own column."""
    db = get_db()
    col = _own_removed_column(db, cid, g.user)
    if (request.form.get("confirm_name") or "").strip().lower() != col["name"].lower():
        flash("The name you typed does not match, so nothing was erased.", "error")
    else:
        backup_file = make_backup("before-erase_")
        db.execute("DELETE FROM columns WHERE id=?", (cid,))   # its values go with it (CASCADE)
        log(db, "user_column_erase", f"user {g.user['id']}: {col['name']} (backup {os.path.basename(backup_file)})")
        db.commit()
        flash(f"Column '{col['name']}' erased for good. A backup was saved first: "
              f"{os.path.basename(backup_file)}.", "ok")
    return redirect(url_for("records.removed_mine_columns"))


# ---------------------------------------------------------------- my records' attachment files (build 61)
def _record_file_path(stored):
    return os.path.join(config.UPLOAD_DIR, "record_attachments", stored)


def _save_record_file(file_storage, dept):
    """Save one uploaded file for a record attachment column, the same way
    Department Database attachments are saved (allowed type, virus scan,
    size limit). Returns (json value, error)."""
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
    folder = os.path.join(config.UPLOAD_DIR, "record_attachments")
    os.makedirs(folder, exist_ok=True)
    stored = secrets.token_hex(10) + "." + ext
    file_storage.save(os.path.join(folder, stored))
    limit = min(int(dept["attachment_max_mb"] or 10), config.MAX_UPLOAD_MB) * 1024 * 1024
    if os.path.getsize(os.path.join(folder, stored)) > limit:
        os.remove(os.path.join(folder, stored))
        return None, f"'{original}' is too large (max {limit // 1024 // 1024} MB)."
    return json.dumps({"stored": stored, "original": original}), None


def _handle_record_files(dept, cols, values, existing):
    """Uploads, keeps and removals for attachment columns on a record form
    (mirrors the Department Database handling). Returns (errors, saved, to_delete)."""
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
            if not can_use_record_attachments(g.user):
                errors.append(f"'{c['name']}': only users given attachment access can upload a file.")
                values[cid] = existing.get(cid)
                continue
            val, err = _save_record_file(file_storage, dept)
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


def _delete_record_files(stored_list):
    for s in stored_list:
        try:
            os.remove(_record_file_path(s))
        except OSError:
            pass


@bp.route("/records/<int:rid>/attachment/<int:cid>")
@login_required
def download_record_attachment(rid, cid):
    """Download the file in one of a record's attachment columns."""
    rec, _level = _load(rid, "view")
    db = get_db()
    col = db.execute("SELECT * FROM columns WHERE id=? AND department_id=? AND removed_at IS NULL "
                     "AND (user_id IS NULL OR user_id=?)",
                     (cid, rec["department_id"], rec["owner_id"])).fetchone()
    if col is None or col["col_type"] != "attachment":
        abort(404)
    vals = values_for(db, [rid])[rid]
    info = ddb_attachment_info(vals.get(cid))
    if info is None:
        abort(404)
    path = _record_file_path(info["stored"])
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=info["original"])


@bp.route("/records/download")
@login_required
def download():
    db = get_db()
    tab = request.args.get("tab", "mine")
    tab = tab if tab in available_tabs(db, g.user) else "mine"
    q = (request.args.get("q") or "").strip()
    if tab == "department":
        return _download_department_csv(db, g.user, q)
    where, params = tab_clause(db, tab, g.user)
    sq, sp = search_clause(q)
    fq, order, fp, op, _info = list_options(db, g.user, request.args)
    rows = db.execute(rec_select() + " WHERE " + where + sq + fq + " ORDER BY " + order,
                      params + sp + fp + op).fetchall()
    # A selection (ids=1,2,3) downloads only those records; without it, all
    # the records the current filters match are downloaded, as before.
    ids = request.args.get("ids")
    if ids:
        idset = {x for x in ids.split(",") if x.isdigit()}
        rows = [r for r in rows if str(r["id"]) in idset]
    header, out = build_csv(db, rows, with_owner=False)
    log(db, "download_csv", f"{len(rows)} records ({tab})")
    db.commit()
    return csv_response(header, out, "records_" + g.user["username"])


# ---------------------------------------------------------------- create / edit
def _form_page(rec, cols, values, version=None, conflict=None):
    return render_template("record_form.html", rec=rec, cols=cols, values=values,
                           version=version, conflict=conflict)


@bp.route("/records/new", methods=["GET", "POST"])
@login_required
def new_record():
    db = get_db()
    dept = g.user["department_id"]
    cols = record_columns(db, dept, g.user["id"])
    if not cols:
        flash("You have no columns yet. Add your first column on the Manage columns page.", "error")
        return redirect(url_for("records.my_columns"))
    if request.method == "POST":
        values, errors = parse_form(cols, request.form)
        dept_row = db.execute("SELECT * FROM departments WHERE id=?", (dept,)).fetchone()
        ferr, saved, _td = _handle_record_files(dept_row, cols, values, {})
        errors += ferr
        if errors:
            _delete_record_files(saved)
            for e in errors:
                flash(e, "error")
            return _form_page(None, cols, _display_values(cols, values))
        rid = create_record(db, g.user, dept, values)
        log(db, "record_add", f"record {rid}")
        db.commit()
        flash("Record saved.", "ok")
        return redirect(url_for("records.detail", rid=rid))
    return _form_page(None, cols, {})


@bp.route("/records/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def edit_record(rid):
    rec, _level = _load(rid, "edit")
    db = get_db()
    cols = record_columns(db, rec["department_id"], rec["owner_id"])
    old = values_for(db, [rid])[rid]
    if request.method == "POST":
        values, errors = parse_form(cols, request.form, old)
        dept_row = db.execute("SELECT * FROM departments WHERE id=?", (rec["department_id"],)).fetchone()
        ferr, saved, to_delete = _handle_record_files(dept_row, cols, values, old)
        errors += ferr
        version = request.form.get("version", type=int) or 0
        if errors:
            _delete_record_files(saved)
            for e in errors:
                flash(e, "error")
            return _form_page(rec, cols, _display_values(cols, values), version)
        result = update_record(db, g.user, rec, cols, values, version)
        if result == "conflict":
            # Somebody saved first. Nothing is overwritten: show the latest values and
            # keep the person's own entries visible so they can apply them again.
            _delete_record_files(saved)
            fresh = get_record(db, rid)
            latest = values_for(db, [rid])[rid]
            last = db.execute("SELECT full_name, at FROM record_history WHERE record_id=? "
                              "ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
            mine = [(c["name"], display_record_value(c, values[c["id"]]) or "") for c in cols
                    if (values[c["id"]] or None) != (latest.get(c["id"]) or None)]
            flash("This record was changed by someone else while you were editing. "
                  "Your changes were NOT saved.", "error")
            return _form_page(fresh, cols, _display_values(cols, latest), fresh["version"],
                              {"by": last["full_name"] if last else "Someone",
                               "at": last["at"] if last else "", "mine": mine})
        if result == "nochange":
            _delete_record_files(saved)
            flash("There was nothing to change.", "ok")
        else:
            _delete_record_files(to_delete)
            log(db, "record_edit", f"record {rid}")
            db.commit()
            flash("Changes saved.", "ok")
        return redirect(url_for("records.detail", rid=rid))
    return _form_page(rec, cols, _display_values(cols, old), rec["version"])


@bp.route("/records/<int:rid>/delete", methods=["POST"])
@login_required
def delete_record(rid):
    rec, _level = _load(rid, "manage")
    db = get_db()
    soft_delete(db, g.user, rec)
    log(db, "record_delete", f"record {rid} moved to the recycle bin")
    # When someone other than the owner deletes the record (a portal admin
    # or an administrative permission user, from the user's own My records
    # page or anywhere else), the owner is told (build 60).
    if rec["owner_id"] != g.user["id"]:
        summary = summaries_for(db, [rec]).get(rec["id"]) or "record"
        notify(db, [rec["owner_id"]],
               f"{g.user['full_name']} deleted your record {summary}.",
               url_for("records.bin_page"))
    db.commit()
    flash("Moved to the recycle bin. You can restore it for "
          f"{config.BIN_DAYS} days.", "ok")
    nxt = (request.form.get("next") or "").strip()
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("records.list_records"))


# ---------------------------------------------------------------- detail page
@bp.route("/records/<int:rid>")
@login_required
def detail(rid):
    rec, level = _load(rid, "view")
    db = get_db()
    cols = record_columns(db, rec["department_id"], rec["owner_id"])
    raw_vals = values_for(db, [rid])[rid]
    vals = _display_values(cols, raw_vals)
    urls = {}
    for c in cols:
        if c["col_type"] == "attachment" and ddb_attachment_info(raw_vals.get(c["id"])):
            urls[c["id"]] = url_for("records.download_record_attachment", rid=rid, cid=c["id"])
    link = db.execute("SELECT pl.* FROM public_links pl JOIN public_link_records plr ON plr.link_id=pl.id "
                      "WHERE plr.record_id=? AND pl.kind='single'", (rid,)).fetchone()
    public_url = public_svg = public_code = None
    if link:
        public_url = external_url(db, "public.view", token=link["token"])
        public_svg = segno.make(public_url, error="m").svg_inline(scale=4, border=1, dark="#10283a", omitsize=True)
        public_code = display_code(link)
    can_manage = level in MANAGE_LEVELS
    can_owner = may_change_owner(g.user, rec) and not rec["deleted_at"]
    return render_template(
        "record_detail.html", rec=rec, level=level, cols=cols, vals=vals, urls=urls,
        can_edit=level in EDIT_LEVELS and not rec["deleted_at"], can_manage=can_manage,
        history=db.execute("SELECT * FROM record_history WHERE record_id=? ORDER BY id DESC LIMIT 100",
                           (rid,)).fetchall(),
        comments=db.execute("SELECT c.*, u.full_name FROM comments c JOIN users u ON u.id=c.user_id "
                            "WHERE record_id=? ORDER BY c.id DESC LIMIT 100", (rid,)).fetchall(),
        repairs=db.execute("SELECT * FROM repairs WHERE record_id=? ORDER BY id DESC", (rid,)).fetchall()
        if rec["repairs_enabled"] else [],
        attachments=db.execute("SELECT a.*, u.full_name AS by_name FROM attachments a "
                               "LEFT JOIN users u ON u.id=a.uploaded_by WHERE record_id=? "
                               "ORDER BY a.id DESC", (rid,)).fetchall(),
        dept_perm={r["department_id"]: r["permission"] for r in db.execute(
            "SELECT department_id, permission FROM record_shares WHERE record_id=?", (rid,))},
        user_shares=db.execute(
            "SELECT s.user_id, s.permission, s.shared_at, u.full_name, u.username, d.name AS dept_name "
            "FROM record_user_shares s JOIN users u ON u.id=s.user_id LEFT JOIN departments d ON d.id=u.department_id "
            "WHERE s.record_id=? ORDER BY u.full_name", (rid,)).fetchall(),
        share_people=db.execute(
            "SELECT u.id, u.full_name, u.username, d.name AS dept_name FROM users u "
            "LEFT JOIN departments d ON d.id=u.department_id WHERE u.is_active=1 AND u.id != ? "
            "ORDER BY d.name, u.full_name", (rec["owner_id"],)).fetchall() if can_manage else [],
        permissions=PERMISSIONS,
        departments=db.execute("SELECT id, name FROM departments ORDER BY name").fetchall(),
        link=link, public_url=public_url, public_svg=public_svg, public_code=public_code,
        public_names=names_for_records(db, [rid]) if can_manage else [],
        can_owner=can_owner, owner_options=owner_candidates(db, g.user, rec) if can_owner else [],
        can_copy=ddb_can_add(db, g.user) and level is not None,
        today=date.today().isoformat())


@bp.route("/records/<int:rid>/owner", methods=["POST"])
@login_required
def set_owner(rid):
    """Portal admin and department admin: give the record to another person."""
    rec, _level = _load(rid, "view")
    db = get_db()
    problem = change_owner(db, g.user, rec, request.form.get("new_owner", type=int) or 0)
    if problem:
        flash(problem, "error")
    else:
        log(db, "record_owner_change", f"record {rid}")
        db.commit()
        flash("The owner was changed.", "ok")
    return redirect(url_for("records.detail", rid=rid))


@bp.route("/records/<int:rid>/share", methods=["POST"])
@login_required
def share(rid):
    """Share with WHOLE departments. Each ticked department gets 'edit' or 'view only'."""
    rec, _level = _load(rid, "manage")
    db = get_db()
    names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM departments")}
    chosen = {int(x): clean_permission(request.form.get(f"perm_{x}"))
              for x in request.form.getlist("dept") if x.isdigit() and int(x) in names}
    current = {r["department_id"] for r in db.execute(
        "SELECT department_id FROM record_shares WHERE record_id=?", (rid,))}
    changed = False
    for d, perm in chosen.items():
        changed = bool(share_with_department(db, g.user, rec, d, names[d], perm)) or changed
    for d in current - set(chosen):
        db.execute("DELETE FROM record_shares WHERE record_id=? AND department_id=?", (rid, d))
        add_history(db, rid, g.user, "unshared", old=names[d])
        changed = True
    if changed:
        log(db, "record_share", f"record {rid}")
    db.commit()
    flash("Sharing updated.", "ok")
    return redirect(url_for("records.detail", rid=rid))


@bp.route("/records/<int:rid>/share-user", methods=["POST"])
@login_required
def share_user(rid):
    """Share with ONE chosen person (edit or view only). Sending it again changes the permission."""
    rec, _level = _load(rid, "manage")
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id=? AND is_active=1",
                        (request.form.get("user_id", type=int) or 0,)).fetchone()
    if target is None:
        flash("Choose a person to share with.", "error")
    elif target["id"] == rec["owner_id"]:
        flash("That person already owns this record.", "error")
    else:
        result = share_with_user(db, g.user, rec, target, request.form.get("permission"))
        if result:
            log(db, "record_share_user", f"record {rid} -> {target['username']}")
            db.commit()
            flash(f"Shared with {target['full_name']}." if result == "new" else "Permission changed.", "ok")
        else:
            flash("Nothing changed.", "ok")
    return redirect(url_for("records.detail", rid=rid))


@bp.route("/records/<int:rid>/share-user/<int:uid>/remove", methods=["POST"])
@login_required
def unshare_user(rid, uid):
    rec, _level = _load(rid, "manage")
    db = get_db()
    row = db.execute("SELECT u.full_name FROM record_user_shares s JOIN users u ON u.id=s.user_id "
                     "WHERE s.record_id=? AND s.user_id=?", (rid, uid)).fetchone()
    if row:
        db.execute("DELETE FROM record_user_shares WHERE record_id=? AND user_id=?", (rid, uid))
        add_history(db, rid, g.user, "unshared_user", old=row["full_name"])
        log(db, "record_unshare_user", f"record {rid} -> user {uid}")
        db.commit()
        flash(f"Stopped sharing with {row['full_name']}.", "ok")
    return redirect(url_for("records.detail", rid=rid))


# ---------------------------------------------------------------- repair log
@bp.route("/records/<int:rid>/repairs", methods=["POST"])
@login_required
def add_repair(rid):
    rec, _level = _load(rid, "edit")
    if not rec["repairs_enabled"]:
        abort(404)                                    # this department does not use a repair log
    db = get_db()
    date_in = (request.form.get("date_in") or date.today().isoformat()).strip()
    problem = (request.form.get("problem") or "").strip()[:500]
    fixed_by = (request.form.get("fixed_by") or "").strip()[:200]
    cost = (request.form.get("cost") or "").strip().replace(",", "")
    date_back = (request.form.get("date_back") or "").strip() or None
    try:
        for d in (date_in, date_back):
            if d:
                datetime.strptime(d, "%Y-%m-%d")
        if cost:
            float(cost)
    except ValueError:
        flash("Check the dates and the cost: dates must be valid and cost must be a number.", "error")
        return redirect(url_for("records.detail", rid=rid))
    if not problem:
        flash("Describe the problem for the repair entry.", "error")
        return redirect(url_for("records.detail", rid=rid))
    db.execute("INSERT INTO repairs(record_id,date_in,problem,fixed_by,cost,date_back,created_by)"
               " VALUES (?,?,?,?,?,?,?)", (rid, date_in, problem, fixed_by, cost or None, date_back, g.user["id"]))
    add_history(db, rid, g.user, "repair_added", new=problem)
    db.commit()
    flash("Repair entry added.", "ok")
    return redirect(url_for("records.detail", rid=rid))


@bp.route("/records/<int:rid>/repairs/<int:rep>/return", methods=["POST"])
@login_required
def return_repair(rid, rep):
    _load(rid, "edit")
    db = get_db()
    db.execute("UPDATE repairs SET date_back=? WHERE id=? AND record_id=? AND date_back IS NULL",
               (date.today().isoformat(), rep, rid))
    add_history(db, rid, g.user, "repair_returned")
    db.commit()
    flash("Marked as back from repair.", "ok")
    return redirect(url_for("records.detail", rid=rid))


@bp.route("/records/<int:rid>/repairs/<int:rep>/delete", methods=["POST"])
@login_required
def delete_repair(rid, rep):
    _load(rid, "manage")
    db = get_db()
    db.execute("DELETE FROM repairs WHERE id=? AND record_id=?", (rep, rid))
    add_history(db, rid, g.user, "repair_removed")
    db.commit()
    flash("Repair entry removed.", "ok")
    return redirect(url_for("records.detail", rid=rid))


# ---------------------------------------------------------------- attachments
def _accept_upload(db, rec, f, say_empty=False):
    """Check ONE uploaded file (type, size, virus scan). Returns {name, ext, size, scan} or None.
    The reason for a refusal is shown to the person with flash()."""
    rid = rec["id"]
    limit = min(rec["attachment_max_mb"], config.MAX_UPLOAD_MB) * 1024 * 1024
    shown = os.path.basename(f.filename.replace("\\", "/"))[:150]
    ext = shown.rsplit(".", 1)[-1].lower() if "." in shown else ""
    if ext not in config.ALLOWED_EXTENSIONS:
        flash(f"'{shown}': this file type is not allowed.", "error")
        return None
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size == 0:
        if say_empty:
            flash(f"'{shown}' is empty.", "error")
        return None
    if size > limit:
        flash(f"'{shown}' is larger than the {limit // 1048576} MB limit.", "error")
        return None
    scan_status = None
    if scanner.enabled():                              # virus scan before anything is stored
        verdict, detail_text = scanner.scan_stream(f.stream)
        f.seek(0)
        if verdict == "infected":
            flash(f"'{shown}' was refused: a virus was found ({detail_text}).", "error")
            log(db, "virus_blocked", f"{shown}: {detail_text} (record {rid})")
            notify(db, admin_ids(db), f"A virus was blocked in an upload by {g.user['full_name']}: {shown}.",
                   "/admin/activity")
            return None
        if verdict == "error":
            flash(f"'{shown}' could not be scanned, so it was not uploaded. Tell the admin ({detail_text}).", "error")
            log(db, "scan_error", f"{shown}: {detail_text}")
            return None
        scan_status = "clean"
    return {"name": shown, "ext": ext, "size": size, "scan": scan_status}


@bp.route("/records/<int:rid>/attachments", methods=["POST"])
@login_required
def add_attachment(rid):
    rec, _level = _load(rid, "edit")
    if not rec["attachments_enabled"]:
        abort(403)
    db = get_db()
    folder = os.path.join(config.UPLOAD_DIR, str(rid))
    saved = 0
    for f in request.files.getlist("files"):
        if not f or not f.filename:
            continue
        info = _accept_upload(db, rec, f)
        if info is None:
            continue
        os.makedirs(folder, exist_ok=True)
        stored = uuid.uuid4().hex + "." + info["ext"]          # random name on disk
        f.save(os.path.join(folder, stored))
        db.execute("INSERT INTO attachments(record_id,original_name,stored_name,size,uploaded_by,scan_status)"
                   " VALUES (?,?,?,?,?,?)", (rid, info["name"], stored, info["size"], g.user["id"], info["scan"]))
        add_history(db, rid, g.user, "attachment_added", new=info["name"])
        saved += 1
    db.commit()
    if saved:
        flash(f"{saved} file(s) uploaded.", "ok")
    return redirect(url_for("records.detail", rid=rid))


@bp.route("/attachments/<int:aid>/replace", methods=["POST"])
@login_required
def replace_attachment(aid):
    """Swap an attached file for a new version. Allowed for everyone who may edit the record
    (owner, admin, and people it is shared with for EDIT). It is written in the edit history."""
    db = get_db()
    att = db.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
    if att is None:
        abort(404)
    rec, _level = _load(att["record_id"], "edit")
    if not rec["attachments_enabled"]:
        abort(403)
    rid = rec["id"]
    back = redirect(url_for("records.detail", rid=rid))
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Choose the new file first.", "error")
        return back
    info = _accept_upload(db, rec, f, say_empty=True)
    if info is None:
        return back
    folder = os.path.join(config.UPLOAD_DIR, str(rid))
    os.makedirs(folder, exist_ok=True)
    stored = uuid.uuid4().hex + "." + info["ext"]
    f.save(os.path.join(folder, stored))
    db.execute("UPDATE attachments SET original_name=?, stored_name=?, size=?, uploaded_by=?, scan_status=?, "
               "uploaded_at=datetime('now','localtime') WHERE id=?",
               (info["name"], stored, info["size"], g.user["id"], info["scan"], aid))
    add_history(db, rid, g.user, "attachment_replaced", old=att["original_name"], new=info["name"])
    log(db, "attachment_replace", f"record {rid}: {att['original_name']} -> {info['name']}")
    notify(db, [rec["owner_id"]], f"{g.user['full_name']} replaced the file '{att['original_name']}' on a record.",
           f"/records/{rid}", skip=g.user["id"])
    db.commit()
    try:                                                    # the old file is removed only after the new one is saved
        os.remove(os.path.join(folder, att["stored_name"]))
    except OSError:
        pass
    flash("File replaced.", "ok")
    return back


@bp.route("/attachments/<int:aid>")
@login_required
def download_attachment(aid):
    db = get_db()
    att = db.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
    if att is None:
        abort(404)
    _load(att["record_id"], "view")
    path = os.path.join(config.UPLOAD_DIR, str(att["record_id"]), att["stored_name"])
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=att["original_name"])


@bp.route("/attachments/<int:aid>/delete", methods=["POST"])
@login_required
def delete_attachment(aid):
    db = get_db()
    att = db.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
    if att is None:
        abort(404)
    _load(att["record_id"], "edit")
    try:
        os.remove(os.path.join(config.UPLOAD_DIR, str(att["record_id"]), att["stored_name"]))
    except OSError:
        pass
    db.execute("DELETE FROM attachments WHERE id=?", (aid,))
    add_history(db, att["record_id"], g.user, "attachment_removed", old=att["original_name"])
    db.commit()
    flash("Attachment removed.", "ok")
    return redirect(url_for("records.detail", rid=att["record_id"]))


# ---------------------------------------------------------------- recycle bin
@bp.route("/bin")
@login_required
def bin_page():
    """Recycle bin. Portal admin / permission user: two tabs, Records and Users.
    Everyone else: only their own deleted records, no Users tab.
    The Records tab lists everything that was deleted and can be restored:
    personal records, Department Database rows, application letters,
    invoices and item requests.
    Before this fix it only listed personal records, so a deleted Department
    Database row never appeared here at all."""
    db = get_db()
    portal = is_portal_admin(g.user)
    tab = request.args.get("tab", "records")
    if tab not in ("records", "users"):
        tab = "records"
    if tab == "users" and not portal:
        tab = "records"
    if tab == "users":
        rows = db.execute("SELECT u.*, d.name AS department_name, "
                          "(SELECT full_name FROM users WHERE id=u.deleted_by) AS deleted_by_name "
                          "FROM users u LEFT JOIN departments d ON d.id=u.department_id "
                          "WHERE u.is_deleted=1 AND u.bin_purged=0 ORDER BY u.deleted_at DESC").fetchall()
        users = []
        for r in rows:
            erase = datetime.strptime(r["deleted_at"], "%Y-%m-%d %H:%M:%S") + timedelta(days=config.BIN_DAYS) if r["deleted_at"] else None
            users.append(dict(r, erase_on=erase.strftime("%d %b %Y") if erase else "",
                              days_left=(erase - datetime.now()).days if erase else 0))
        return render_template("bin.html", items=[], users=users, tab=tab, portal=portal, days=config.BIN_DAYS)

    def _erase(deleted_at):
        erase = datetime.strptime(deleted_at, "%Y-%m-%d %H:%M:%S") + timedelta(days=config.BIN_DAYS)
        return erase.strftime("%d %b %Y"), (erase - datetime.now()).days

    items = []
    # 1. Personal records (as before).
    where = "r.deleted_at IS NOT NULL" + ("" if portal else " AND r.owner_id=?")
    params = [] if portal else [g.user["id"]]
    rows = db.execute(rec_select(", (SELECT full_name FROM users WHERE id=r.deleted_by) AS deleted_by_name")
                      + " WHERE " + where + " ORDER BY r.deleted_at DESC", params).fetchall()
    sums = summaries_for(db, rows)
    for r in rows:
        erase_on, days_left = _erase(r["deleted_at"])
        items.append(dict(r, summary=sums[r["id"]], erase_on=erase_on, days_left=days_left,
                          kind_label="Personal record",
                          view_url=url_for("records.detail", rid=r["id"]),
                          restore_url=url_for("records.bin_restore", rid=r["id"]),
                          purge_url=url_for("records.bin_purge", rid=r["id"])))
    # 2. Department Database rows. A deleted row is soft-deleted (deleted_at
    # is set) and is erased for good after 30 days, but it never appeared in
    # this bin before — only personal records did.
    where = "r.deleted_at IS NOT NULL" + ("" if portal else " AND r.owner_id=?")
    params = [] if portal else [g.user["id"]]
    drows = db.execute("SELECT r.*, u.full_name AS owner_name, u.is_active AS owner_is_active, "
                       "u.is_deleted AS owner_is_deleted, d.name AS department_name, "
                       "t.name AS tab_name, "
                       "(SELECT full_name FROM users WHERE id=r.deleted_by) AS deleted_by_name "
                       "FROM ddb_rows r JOIN users u ON u.id=r.owner_id "
                       "JOIN departments d ON d.id=r.department_id "
                       "LEFT JOIN ddb_tabs t ON t.id=r.tab_id "
                       "WHERE " + where + " ORDER BY r.deleted_at DESC", params).fetchall()
    for r in drows:
        erase_on, days_left = _erase(r["deleted_at"])
        name = first_text_value(db, r["id"]) or f"Row #{r['id']}"
        items.append(dict(r, summary=name, erase_on=erase_on, days_left=days_left,
                          kind_label="Department row" + (f" · {r['tab_name']}" if r["tab_name"] else ""),
                          view_url=None,
                          restore_url=url_for("records.bin_ddb_restore", rid=r["id"]),
                          purge_url=url_for("records.bin_ddb_purge", rid=r["id"])))
    # 3. Application letters. A deleted application is soft-deleted and is
    # erased for good after 30 days. The owner or the recipient sees it here;
    # a portal admin or permission user sees them all.
    where = "a.deleted_at IS NOT NULL" + ("" if portal else " AND (a.owner_id=? OR a.recipient_id=?)")
    params = [] if portal else [g.user["id"], g.user["id"]]
    arows = db.execute("SELECT a.*, k.name AS kind_name, o.full_name AS owner_name, "
                       "o.is_active AS owner_is_active, o.is_deleted AS owner_is_deleted, "
                       "d.name AS department_name, "
                       "(SELECT full_name FROM users WHERE id=a.deleted_by) AS deleted_by_name "
                       "FROM applications a LEFT JOIN application_kinds k ON k.id=a.kind_id "
                       "JOIN users o ON o.id=a.owner_id "
                       "JOIN departments d ON d.id=a.department_id "
                       "WHERE " + where + " ORDER BY a.deleted_at DESC", params).fetchall()
    for r in arows:
        erase_on, days_left = _erase(r["deleted_at"])
        items.append(dict(r, summary=(r["number"] or "Application") + (f" · {r['kind_name']}" if r["kind_name"] else ""),
                          erase_on=erase_on, days_left=days_left,
                          kind_label="Application letter",
                          view_url=None,
                          restore_url=url_for("records.bin_app_restore", aid=r["id"]),
                          purge_url=url_for("records.bin_app_purge", aid=r["id"])))
    # 4. Invoices. A deleted invoice is soft-deleted and is erased for good
    # after 30 days (build 60). The owner sees it here; a portal admin or
    # permission user sees them all. A draft has no number yet, so its
    # summary says so.
    where = "i.deleted_at IS NOT NULL" + ("" if portal else " AND i.owner_id=?")
    params = [] if portal else [g.user["id"]]
    irows = db.execute("SELECT i.*, t.name AS template_name, o.full_name AS owner_name, "
                       "o.is_active AS owner_is_active, o.is_deleted AS owner_is_deleted, "
                       "d.name AS department_name, "
                       "(SELECT full_name FROM users WHERE id=i.deleted_by) AS deleted_by_name "
                       "FROM invoices i LEFT JOIN invoice_templates t ON t.id=i.template_id "
                       "JOIN users o ON o.id=i.owner_id "
                       "JOIN departments d ON d.id=i.department_id "
                       "WHERE " + where + " ORDER BY i.deleted_at DESC", params).fetchall()
    for r in irows:
        erase_on, days_left = _erase(r["deleted_at"])
        items.append(dict(r, summary=(r["number"] or "Draft invoice") + (f" · {r['template_name']}" if r["template_name"] else ""),
                          erase_on=erase_on, days_left=days_left,
                          kind_label="Invoice",
                          view_url=None,
                          restore_url=url_for("records.bin_invoice_restore", iid=r["id"]),
                          purge_url=url_for("records.bin_invoice_purge", iid=r["id"])))
    # 5. Item requests. Same shape as invoices (build 60).
    where = "r.deleted_at IS NOT NULL" + ("" if portal else " AND r.owner_id=?")
    params = [] if portal else [g.user["id"]]
    qrows = db.execute("SELECT r.*, k.name AS kind_name, o.full_name AS owner_name, "
                       "o.is_active AS owner_is_active, o.is_deleted AS owner_is_deleted, "
                       "d.name AS department_name, "
                       "(SELECT full_name FROM users WHERE id=r.deleted_by) AS deleted_by_name "
                       "FROM item_requests r LEFT JOIN item_request_kinds k ON k.id=r.kind_id "
                       "JOIN users o ON o.id=r.owner_id "
                       "JOIN departments d ON d.id=r.department_id "
                       "WHERE " + where + " ORDER BY r.deleted_at DESC", params).fetchall()
    for r in qrows:
        erase_on, days_left = _erase(r["deleted_at"])
        items.append(dict(r, summary=(r["number"] or "Item request") + (f" · {r['kind_name']}" if r["kind_name"] else ""),
                          erase_on=erase_on, days_left=days_left,
                          kind_label="Item request",
                          view_url=None,
                          restore_url=url_for("records.bin_request_restore", rid=r["id"]),
                          purge_url=url_for("records.bin_request_purge", rid=r["id"])))
    items.sort(key=lambda it: it["deleted_at"] or "", reverse=True)
    return render_template("bin.html", items=items, users=[], tab=tab, portal=portal, days=config.BIN_DAYS)


def _bin_purge_blocked(db, deleted_by):
    """True when the current user may NOT erase this deleted item for good.
    A permission user cannot erase a record, row or application that he
    deleted himself, that the portal admin deleted, or that any permission
    user deleted. Only the portal admin can erase those."""
    if is_true_admin(g.user) or not deleted_by:
        return False
    if deleted_by == g.user["id"]:
        return True
    deleter = db.execute("SELECT role, can_portal_admin FROM users WHERE id=?", (deleted_by,)).fetchone()
    return bool(deleter and (deleter["role"] == "admin" or deleter["can_portal_admin"]))


@bp.route("/bin/ddb/<int:rid>/restore", methods=["POST"])
@login_required
def bin_ddb_restore(rid):
    """Restore a deleted Department Database row from the Recycle Bin. The
    owner or a department admin of that department can do it."""
    db = get_db()
    row = db.execute("SELECT * FROM ddb_rows WHERE id=?", (rid,)).fetchone()
    if row is None or not row["deleted_at"]:
        abort(404)
    if row["owner_id"] != g.user["id"] and not ddb_is_tab_admin(db, g.user, row["department_id"]):
        abort(403)
    db.execute("UPDATE ddb_rows SET deleted_at=NULL, deleted_by=NULL, version=version+1 WHERE id=?", (rid,))
    ddb_history(db, rid, g.user, "restored")
    log(db, "ddb_restore", f"row {rid} (from the Recycle Bin)")
    db.commit()
    flash("Row restored.", "ok")
    return redirect(url_for("records.bin_page"))


@bp.route("/bin/ddb/<int:rid>/purge", methods=["POST"])
@login_required
def bin_ddb_purge(rid):
    """Erase a deleted Department Database row for good, from the Recycle Bin."""
    db = get_db()
    row = db.execute("SELECT * FROM ddb_rows WHERE id=?", (rid,)).fetchone()
    if row is None or not row["deleted_at"]:
        abort(404)
    if row["owner_id"] != g.user["id"] and not ddb_is_tab_admin(db, g.user, row["department_id"]):
        abort(403)
    if _bin_purge_blocked(db, row["deleted_by"]):
        flash("Only the portal admin can erase this row for good.", "error")
        return redirect(url_for("records.bin_page"))
    purge_ddb_row(db, rid)
    log(db, "ddb_erase", f"row {rid} erased for good")
    db.commit()
    flash("Row erased for good.", "ok")
    return redirect(url_for("records.bin_page"))


@bp.route("/bin/applications/<int:aid>/restore", methods=["POST"])
@login_required
def bin_app_restore(aid):
    """Restore a deleted application letter from the Recycle Bin. The owner,
    the recipient, the HR & Admin department admin or the portal admin can
    do it."""
    db = get_db()
    app = db.execute("SELECT * FROM applications WHERE id=?", (aid,)).fetchone()
    if app is None or not app["deleted_at"]:
        abort(404)
    from routes_applications import _is_hr_dept_admin
    if not (is_portal_admin(g.user) or app["owner_id"] == g.user["id"]
            or app["recipient_id"] == g.user["id"] or _is_hr_dept_admin(db, g.user)):
        abort(403)
    db.execute("UPDATE applications SET deleted_at=NULL, deleted_by=NULL, updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    db.execute("INSERT INTO application_history(application_id,user_id,username,full_name,action,field,old_value,new_value) VALUES (?,?,?,?,?,?,?,?)",
               (aid, g.user["id"], g.user["username"], g.user["full_name"], "restored", "Application", app["number"] or "", "restored"))
    log(db, "application_restore", app["number"] or str(aid))
    db.commit()
    flash(f"Application {app['number']} restored.", "ok")
    return redirect(url_for("records.bin_page"))


@bp.route("/bin/applications/<int:aid>/purge", methods=["POST"])
@login_required
def bin_app_purge(aid):
    """Erase a deleted application letter for good, from the Recycle Bin."""
    db = get_db()
    app = db.execute("SELECT * FROM applications WHERE id=?", (aid,)).fetchone()
    if app is None or not app["deleted_at"]:
        abort(404)
    if not (is_portal_admin(g.user) or app["owner_id"] == g.user["id"]
            or app["recipient_id"] == g.user["id"]):
        abort(403)
    if _bin_purge_blocked(db, app["deleted_by"]):
        flash("Only the portal admin can erase this application for good.", "error")
        return redirect(url_for("records.bin_page"))
    purge_application(db, aid)
    log(db, "application_erase", f"{app['number']} erased for good")
    db.commit()
    flash(f"Application {app['number']} erased for good.", "ok")
    return redirect(url_for("records.bin_page"))


@bp.route("/bin/invoices/<int:iid>/restore", methods=["POST"])
@login_required
def bin_invoice_restore(iid):
    """Restore a deleted invoice from the Recycle Bin. The owner or a
    portal admin can do it; the invoice comes back with its number and
    its chain exactly as it was."""
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if inv is None or not inv["deleted_at"]:
        abort(404)
    if not (is_portal_admin(g.user) or inv["owner_id"] == g.user["id"]):
        abort(403)
    db.execute("UPDATE invoices SET deleted_at=NULL, deleted_by=NULL, updated_at=datetime('now','localtime') WHERE id=?", (iid,))
    log(db, "invoice_restore", inv["number"] or "draft")
    db.commit()
    flash(f"Invoice {inv['number'] or 'draft'} restored.", "ok")
    return redirect(url_for("records.bin_page"))


@bp.route("/bin/invoices/<int:iid>/purge", methods=["POST"])
@login_required
def bin_invoice_purge(iid):
    """Erase a deleted invoice for good, from the Recycle Bin. The same
    rule as for records: a permission user cannot erase an invoice he
    deleted himself, one the portal admin deleted, or one another
    permission user deleted — only the portal admin can erase those."""
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if inv is None or not inv["deleted_at"]:
        abort(404)
    if not (is_portal_admin(g.user) or inv["owner_id"] == g.user["id"]):
        abort(403)
    if _bin_purge_blocked(db, inv["deleted_by"]):
        flash("Only the portal admin can erase this invoice for good.", "error")
        return redirect(url_for("records.bin_page"))
    purge_invoice(db, iid)
    log(db, "invoice_erase", f"{inv['number'] or 'draft'} erased for good")
    db.commit()
    flash(f"Invoice {inv['number'] or 'draft'} erased for good.", "ok")
    return redirect(url_for("records.bin_page"))


@bp.route("/bin/requests/<int:rid>/restore", methods=["POST"])
@login_required
def bin_request_restore(rid):
    """Restore a deleted item request from the Recycle Bin. The owner or a
    portal admin can do it; the request comes back with its number and
    its chain exactly as it was."""
    db = get_db()
    req = db.execute("SELECT * FROM item_requests WHERE id=?", (rid,)).fetchone()
    if req is None or not req["deleted_at"]:
        abort(404)
    if not (is_portal_admin(g.user) or req["owner_id"] == g.user["id"]):
        abort(403)
    db.execute("UPDATE item_requests SET deleted_at=NULL, deleted_by=NULL, updated_at=datetime('now','localtime') WHERE id=?", (rid,))
    log(db, "item_request_restore", req["number"] or "request")
    db.commit()
    flash(f"Item request {req['number'] or 'request'} restored.", "ok")
    return redirect(url_for("records.bin_page"))


@bp.route("/bin/requests/<int:rid>/purge", methods=["POST"])
@login_required
def bin_request_purge(rid):
    """Erase a deleted item request for good, from the Recycle Bin. The same
    rule as for records: a permission user cannot erase a request he
    deleted himself, one the portal admin deleted, or one another
    permission user deleted — only the portal admin can erase those."""
    db = get_db()
    req = db.execute("SELECT * FROM item_requests WHERE id=?", (rid,)).fetchone()
    if req is None or not req["deleted_at"]:
        abort(404)
    if not (is_portal_admin(g.user) or req["owner_id"] == g.user["id"]):
        abort(403)
    if _bin_purge_blocked(db, req["deleted_by"]):
        flash("Only the portal admin can erase this request for good.", "error")
        return redirect(url_for("records.bin_page"))
    purge_request(db, rid)
    log(db, "item_request_erase", f"{req['number'] or 'request'} erased for good")
    db.commit()
    flash(f"Item request {req['number'] or 'request'} erased for good.", "ok")
    return redirect(url_for("records.bin_page"))


@bp.route("/bin/<int:rid>/restore", methods=["POST"])
@login_required
def bin_restore(rid):
    rec, _level = _load(rid, "manage")
    if not rec["deleted_at"]:
        abort(400)
    db = get_db()
    restore(db, g.user, rec)
    log(db, "record_restore", f"record {rid}")
    notify_admin_task(db, g.user,
                      f"{g.user['full_name']} restored a deleted record.",
                      url_for("records.detail", rid=rid))
    db.commit()
    flash("Record restored.", "ok")
    return redirect(url_for("records.bin_page"))


@bp.route("/bin/<int:rid>/purge", methods=["POST"])
@login_required
def bin_purge(rid):
    rec, _level = _load(rid, "manage")
    if not rec["deleted_at"]:
        abort(400)
    db = get_db()
    # A permission user cannot erase for good a record he deleted himself, a
    # record the portal admin deleted, or a record any permission user deleted.
    # Only the portal admin can erase those. He can still erase a record a
    # regular user deleted himself.
    if not is_true_admin(g.user) and rec["deleted_by"]:
        deleter = db.execute("SELECT role, can_portal_admin FROM users WHERE id=?", (rec["deleted_by"],)).fetchone()
        if rec["deleted_by"] == g.user["id"] or (deleter and (deleter["role"] == "admin" or deleter["can_portal_admin"])):
            flash("Only the portal admin can erase this record for good.", "error")
            return redirect(url_for("records.bin_page"))
    purge_record(db, rid)
    log(db, "record_erase", f"record {rid} erased for good")
    notify_admin_task(db, g.user,
                      f"{g.user['full_name']} erased a deleted record for good.",
                      url_for("records.bin_page"))
    db.commit()
    flash("Record erased for good.", "ok")
    return redirect(url_for("records.bin_page"))


# ---------------------------------------------------------------- reminders
@bp.route("/reminders")
@login_required
def reminders():
    db = get_db()
    days = min(max(request.args.get("days", config.REMINDER_DAYS, type=int), 1), 365)   # 1, 3, 7, 15, 30 ... 365
    today = date.today()
    soon = reminder_rows(db, g.user, today.isoformat(), (today + timedelta(days=days)).isoformat())
    gone = reminder_rows(db, g.user, "0000-01-01", (today - timedelta(days=1)).isoformat(),
                         newest_first=True, limit=200)
    sums = summaries_for(db, list(soon) + list(gone))

    def prep(rows):
        return [dict(r, summary=sums[r["id"]],
                     left=(datetime.strptime(r["reminder_date"][:10], "%Y-%m-%d").date() - today).days)
                for r in rows if _valid_date(r["reminder_date"])]
    return render_template("reminders.html", soon=prep(soon), expired=prep(gone), days=days)


def _valid_date(text):
    try:
        datetime.strptime((text or "")[:10], "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- recycle bin: users tab
@bp.route("/bin/users/<int:user_id>/restore", methods=["POST"])
@admin_required
def bin_user_restore(user_id):
    """Restore a deleted user: he can work as before, name green again."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None or not row["is_deleted"] or row["bin_purged"]:
        abort(404)
    db.execute("UPDATE users SET is_deleted=0, deleted_at=NULL, deleted_by=NULL, bin_purged=0, "
               "is_active=1, approval_status='approved' WHERE id=?", (user_id,))
    log(db, "user_restore", row["username"])
    notify_admin_task(db, g.user,
                      f"{g.user['full_name']} restored the user {row['full_name']} ({row['username']}).",
                      url_for("records.bin_page", tab="users"))
    db.commit()
    flash(f"{row['full_name']} is restored and can work as before.", "ok")
    return redirect(url_for("records.bin_page", tab="users"))


@bp.route("/bin/users/<int:user_id>/purge", methods=["POST"])
@admin_required
def bin_user_purge(user_id):
    """Delete a deleted user from the Recycle Bin for good.
    The popup asks: 'You want to delete this user all work from the portal too?'
    Yes (delete_work=1): his work is deleted immediately, then the account.
    No (delete_work=0): the account leaves the bin list, his work stays (name in
    red) until the 30 days end, when it vanishes with the account.
    A permission user cannot erase a true portal admin's account, or his own,
    or an account deleted by any permission user (including himself). Only the
    portal admin can erase those. In practice a permission user cannot erase
    any user account from the Recycle Bin, since accounts are only ever
    deleted by the portal admin or a permission user."""
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None or not row["is_deleted"] or row["bin_purged"]:
        abort(404)
    if not is_true_admin(g.user) and (is_true_admin(row) or user_id == g.user["id"]):
        abort(403)
    if not is_true_admin(g.user) and row["deleted_by"]:
        deleter = db.execute("SELECT role, can_portal_admin FROM users WHERE id=?", (row["deleted_by"],)).fetchone()
        if row["deleted_by"] == g.user["id"] or (deleter and (deleter["role"] == "admin" or deleter["can_portal_admin"])):
            flash("Only the portal admin can erase this user for good.", "error")
            return redirect(url_for("records.bin_page", tab="users"))
    delete_work = request.form.get("delete_work") == "1"
    purge_user_account(db, user_id, delete_work=delete_work)
    log(db, "user_purge" if delete_work else "user_purge_keep_work", row["username"])
    notify_admin_task(db, g.user,
                      f"{g.user['full_name']} erased the user {row['full_name']} ({row['username']}) for good"
                      + (" and all their work." if delete_work else "."),
                      url_for("records.bin_page", tab="users"))
    db.commit()
    if delete_work:
        flash(f"{row['full_name']} and all their work were deleted from the portal.", "ok")
    else:
        flash(f"{row['full_name']} was removed from the Recycle Bin. Their work stays in the portal (name in red) until the 30 days end.", "ok")
    return redirect(url_for("records.bin_page", tab="users"))
