"""
routes_records.py - pages every user sees: records, detail, sharing, repair log,
attachments, recycle bin, reminders and QR labels.

Used by: app.py (registers it).   Uses: auth.py, core.py, models.py, utils.py, config.py
Templates: records_list, record_form, record_detail, bin, reminders, qr_label.

Permission levels (see core.access_level):
  owner      - made the record: edit, share, delete, hand over, public QR
  shared     - member of a department it is shared with: view and edit every field
  admin      - everything
  supervisor - department admin of the record's department: view and comment/suggest only
  viewer     - allowed to view another department: view and comment/suggest only
"""
import os
import uuid
from datetime import date, datetime, timedelta

import segno
from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   send_file, url_for)

import config
from auth import login_required
import scanner
from core import (EDIT_LEVELS, MANAGE_LEVELS, PERMISSIONS, PERM_WORDS, clean_permission, share_with_department,
                  share_with_user, access_level, add_history, admin_ids, build_csv,
                  column_names, create_record, dept_member_ids, filter_clause, get_columns, get_record,
                  names_for_records, notify, parse_form, purge_record, rec_select, reminder_rows,
                  restore, search_clause, soft_delete, sort_clause, summaries_for, table_context,
                  update_record, values_for, viewable_departments)
from models import get_db, log
from utils import csv_response, page_info

bp = Blueprint("records", __name__)
TABS = ("mine", "shared_by_me", "shared_with_me", "department", "viewing")


def available_tabs(db, user):
    """Tabs this user can use (department / viewing only appear when allowed)."""
    tabs = ["mine", "shared_by_me", "shared_with_me"]
    if user["is_dept_admin"]:
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
    if tab == "department" and user["is_dept_admin"]:
        return "r.deleted_at IS NULL AND r.department_id=?", [user["department_id"]]
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


def label_items(db, rows):
    """Data for printable QR labels (also used by the admin label page)."""
    sums = summaries_for(db, rows)
    items = []
    for r in rows:
        url = url_for("records.detail", rid=r["id"], _external=True)
        svg = segno.make(url, error="m").svg_inline(scale=4, border=1, dark="#10283a", omitsize=True)
        items.append({"id": r["id"], "title": sums[r["id"]], "dept": r["department_name"],
                      "svg": svg, "url": url})
    return items


# ---------------------------------------------------------------- lists
@bp.route("/")
@login_required
def home():
    if g.user["role"] == "admin":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("records.list_records"))


@bp.route("/records")
@login_required
def list_records():
    db = get_db()
    tabs = available_tabs(db, g.user)
    tab = request.args.get("tab", "mine")
    tab = tab if tab in tabs else "mine"
    q = (request.args.get("q") or "").strip()
    counts = {}
    for t in tabs:
        where, params = tab_clause(db, t, g.user)
        counts[t] = db.execute("SELECT COUNT(*) FROM records r WHERE " + where, params).fetchone()[0]
    where, params = tab_clause(db, tab, g.user)
    sq, sp = search_clause(q)
    fq, order, fp, op, info = list_options(db, g.user, request.args)
    total = db.execute("SELECT COUNT(*) FROM records r WHERE " + where + sq + fq, params + sp + fp).fetchone()[0]
    page, pages, offset = page_info(total, request.args.get("page", 1, type=int), config.PER_PAGE)
    rows = db.execute(rec_select() + " WHERE " + where + sq + fq + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                      params + sp + fp + op + [config.PER_PAGE, offset]).fetchall()
    today = date.today()
    soon = len(reminder_rows(db, g.user, today.isoformat(),
                             (today + timedelta(days=config.REMINDER_DAYS)).isoformat()))
    saved = db.execute("SELECT * FROM saved_views WHERE user_id=? AND page='records' ORDER BY name",
                       (g.user["id"],)).fetchall()
    keep = {k: v for k, v in request.args.items() if k != "page"}
    return render_template("records_list.html", ctx=table_context(db, rows, g.user), tab=tab, tabs=tabs, q=q,
                           counts=counts, total=total, page=page, pages=pages, soon=soon,
                           reminder_days=config.REMINDER_DAYS, info=info, names=column_names(db, g.user),
                           saved=saved, keep=keep, view_page="records",
                           departments=db.execute("SELECT id, name FROM departments ORDER BY name").fetchall())


@bp.route("/records/download")
@login_required
def download():
    db = get_db()
    tab = request.args.get("tab", "mine")
    tab = tab if tab in available_tabs(db, g.user) else "mine"
    q = (request.args.get("q") or "").strip()
    where, params = tab_clause(db, tab, g.user)
    sq, sp = search_clause(q)
    fq, order, fp, op, _info = list_options(db, g.user, request.args)
    rows = db.execute(rec_select() + " WHERE " + where + sq + fq + " ORDER BY " + order,
                      params + sp + fp + op).fetchall()
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
    cols = get_columns(db, dept)
    if not cols:
        flash("Your department has no record columns yet. Ask the admin to add them.", "error")
        return redirect(url_for("records.list_records"))
    if request.method == "POST":
        values, errors = parse_form(cols, request.form)
        if errors:
            for e in errors:
                flash(e, "error")
            return _form_page(None, cols, values)
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
    cols = get_columns(db, rec["department_id"])
    old = values_for(db, [rid])[rid]
    if request.method == "POST":
        values, errors = parse_form(cols, request.form, old)
        version = request.form.get("version", type=int) or 0
        if errors:
            for e in errors:
                flash(e, "error")
            return _form_page(rec, cols, values, version)
        result = update_record(db, g.user, rec, cols, values, version)
        if result == "conflict":
            # Somebody saved first. Nothing is overwritten: show the latest values and
            # keep the person's own entries visible so they can apply them again.
            fresh = get_record(db, rid)
            latest = values_for(db, [rid])[rid]
            last = db.execute("SELECT full_name, at FROM record_history WHERE record_id=? "
                              "ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
            mine = [(c["name"], values[c["id"]] or "") for c in cols
                    if (values[c["id"]] or None) != (latest.get(c["id"]) or None)]
            flash("This record was changed by someone else while you were editing. "
                  "Your changes were NOT saved.", "error")
            return _form_page(fresh, cols, latest, fresh["version"],
                              {"by": last["full_name"] if last else "Someone",
                               "at": last["at"] if last else "", "mine": mine})
        if result == "nochange":
            flash("There was nothing to change.", "ok")
        else:
            log(db, "record_edit", f"record {rid}")
            db.commit()
            flash("Changes saved.", "ok")
        return redirect(url_for("records.detail", rid=rid))
    return _form_page(rec, cols, old, rec["version"])


@bp.route("/records/<int:rid>/delete", methods=["POST"])
@login_required
def delete_record(rid):
    rec, _level = _load(rid, "manage")
    db = get_db()
    soft_delete(db, g.user, rec)
    log(db, "record_delete", f"record {rid} moved to the recycle bin")
    db.commit()
    flash("Moved to the recycle bin. You can restore it for "
          f"{config.BIN_DAYS} days.", "ok")
    return redirect(url_for("records.list_records"))


# ---------------------------------------------------------------- detail page
@bp.route("/records/<int:rid>")
@login_required
def detail(rid):
    rec, level = _load(rid, "view")
    db = get_db()
    cols = get_columns(db, rec["department_id"])
    vals = values_for(db, [rid])[rid]
    url = url_for("records.detail", rid=rid, _external=True)
    qr_svg = segno.make(url, error="m").svg_inline(scale=4, border=1, dark="#10283a", omitsize=True)
    link = db.execute("SELECT pl.* FROM public_links pl JOIN public_link_records plr ON plr.link_id=pl.id "
                      "WHERE plr.record_id=? AND pl.kind='single'", (rid,)).fetchone()
    public_url = public_svg = None
    if link:
        public_url = url_for("public.view", token=link["token"], _external=True)
        public_svg = segno.make(public_url, error="m").svg_inline(scale=4, border=1, dark="#10283a", omitsize=True)
    can_manage = level in MANAGE_LEVELS
    return render_template(
        "record_detail.html", rec=rec, level=level, cols=cols, vals=vals, qr_svg=qr_svg,
        can_edit=level in EDIT_LEVELS and not rec["deleted_at"], can_manage=can_manage,
        history=db.execute("SELECT * FROM record_history WHERE record_id=? ORDER BY id DESC LIMIT 100",
                           (rid,)).fetchall(),
        comments=db.execute("SELECT c.*, u.full_name FROM comments c JOIN users u ON u.id=c.user_id "
                            "WHERE record_id=? ORDER BY c.id DESC LIMIT 100", (rid,)).fetchall(),
        repairs=db.execute("SELECT * FROM repairs WHERE record_id=? ORDER BY id DESC", (rid,)).fetchall(),
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
        link=link, public_url=public_url, public_svg=public_svg,
        public_names=names_for_records(db, [rid]) if can_manage else [],
        transfer=db.execute("SELECT t.*, u.full_name AS to_name FROM transfers t JOIN users u ON u.id=t.to_user "
                            "WHERE t.record_id=? AND t.status='pending'", (rid,)).fetchone(),
        people=db.execute("SELECT id, full_name, username FROM users WHERE is_active=1 AND id != ? "
                          "ORDER BY full_name", (rec["owner_id"],)).fetchall() if can_manage else [],
        today=date.today().isoformat())


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
    _load(rid, "edit")
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
    db = get_db()
    where = "r.deleted_at IS NOT NULL" + ("" if g.user["role"] == "admin" else " AND r.owner_id=?")
    params = [] if g.user["role"] == "admin" else [g.user["id"]]
    rows = db.execute(rec_select(", (SELECT full_name FROM users WHERE id=r.deleted_by) AS deleted_by_name")
                      + " WHERE " + where + " ORDER BY r.deleted_at DESC", params).fetchall()
    sums = summaries_for(db, rows)
    items = []
    for r in rows:
        erase = datetime.strptime(r["deleted_at"], "%Y-%m-%d %H:%M:%S") + timedelta(days=config.BIN_DAYS)
        items.append(dict(r, summary=sums[r["id"]], erase_on=erase.strftime("%d %b %Y"),
                          days_left=(erase - datetime.now()).days))
    return render_template("bin.html", items=items, days=config.BIN_DAYS)


@bp.route("/bin/<int:rid>/restore", methods=["POST"])
@login_required
def bin_restore(rid):
    rec, _level = _load(rid, "manage")
    if not rec["deleted_at"]:
        abort(400)
    db = get_db()
    restore(db, g.user, rec)
    log(db, "record_restore", f"record {rid}")
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
    purge_record(db, rid)
    log(db, "record_erase", f"record {rid} erased for good")
    db.commit()
    flash("Record erased for good.", "ok")
    return redirect(url_for("records.bin_page"))


# ---------------------------------------------------------------- reminders and labels
@bp.route("/reminders")
@login_required
def reminders():
    db = get_db()
    days = min(max(request.args.get("days", config.REMINDER_DAYS, type=int), 1), 365)
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


@bp.route("/records/<int:rid>/label")
@login_required
def label(rid):
    rec, _level = _load(rid, "view")
    return render_template("qr_label.html", items=label_items(get_db(), [rec]), many=False)


@bp.route("/labels")
@login_required
def labels():
    """Printable QR labels for all of the user's own records (up to 300)."""
    db = get_db()
    rows = db.execute(rec_select() + " WHERE r.deleted_at IS NULL AND r.owner_id=? "
                      "ORDER BY r.id LIMIT 300", (g.user["id"],)).fetchall()
    return render_template("qr_label.html", items=label_items(db, rows), many=True)
