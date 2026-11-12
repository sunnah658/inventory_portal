"""
routes_applications.py - Application Letters (NEW in this version, section 60 in README).

A new page inside More, for all users EXCEPT the portal admin. A dept admin
makes an Application Letter kind for their OWN department (like an invoice
template / Item Request kind). A user picks a kind, fills in the leave
(from date, to date, reason, letter body) and sends the application to a
SPECIFIC user in their OWN department — a department user or the person with
Department admin permission of that department. That person (the checker)
checks it, uploads their signature, then forwards it to an HR & Admin user.
HR approves or rejects it and uploads their signature. So the flow is:
Pending (with the checker) -> Checked (checker signed and forwarded, with
HR) -> Approved / Rejected. A new application starts as Pending and gets a
number like LV-0001 (sequential per kind). The owner can edit their own
application while it is still Pending.

The document is a formal application letter (not an invoice): a letterhead,
Ref + date, To (the checker, with the applicant's department), Subject, the
body, the applicant's signature (name, designation, department, company),
and a FOR OFFICE USE section with the HR note and two signature blocks side
by side — Checked By (the checker's uploaded signature image above their
name and designation) and Approved By (the HR approver's uploaded signature
image above their name and designation). The owner's designation comes
from their user account and is filled in automatically. The kind carries
its own company name and address for the letterhead (blank = portal
defaults). An approved application shows the grey APPROVED seal on the PDF;
a rejected one shows the grey REJECTED stamp. There is no separate Status
or Date line at the bottom of the letter.

Sub-tabs on the page: My applications (only the current user's), All
applications, Received (only the applications sent TO the current user —
the checker while Pending, the HR approver once Checked). In All
applications, administrative permission users and HR & Admin users see ALL
departments' applications; users of other departments see only their own
department's. The portal admin does not use this page at all, except that
they may open an application and delete it.

Public QR for applications: HRC- + random 5-digit code, e.g. HRC-48392 —
the same random-code system as invoices, requests and records, unique across
all of them. A new scan link kills the old code.

Used by: app.py (registers it). Uses: core.py, auth.py, models.py, exports.py, config.py, routes_requests.py (HR helpers)
Templates: application_*.html
"""
import json
import os
import secrets
from datetime import date, datetime

import segno
from flask import (Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for)

import config
import exports
from auth import login_required
from utils import is_portal_admin, is_true_admin
from core import external_url, notify, notify_ddb_task
from models import get_db, log, setting_get
from routes_requests import can_see_all_departments, hr_admin_dept_id, hr_admin_users

bp = Blueprint("applications", __name__)
STATUSES = ["pending", "checked", "approved", "rejected"]
STATUS_LABELS = {"pending": "Pending", "checked": "Checked", "approved": "Approved", "rejected": "Rejected"}
SIG_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]

# ---------------------------------------------------------------- helpers
def _is_dept_admin(user):
    return bool(user and user["is_dept_admin"])

def _dept_admin_required():
    if not _is_dept_admin(g.user):
        abort(403)

@bp.before_request
def _letters_allowed():
    """Application Letters are for all users EXCEPT the portal admin. The
    public code pages (no login) are not affected. The true portal admin
    may still open an application, delete it and download its PDF (they
    can delete it, so they must be able to reach it) — but not the list,
    the kinds, or any other application route."""
    if request.endpoint in ("applications.code_page", "applications.code_pdf"):
        return None
    if g.user is not None and is_true_admin(g.user):
        if request.endpoint in ("applications.detail", "applications.application_delete",
                                "applications.application_pdf"):
            return None
        abort(403)
    return None

def _kind(db, kid):
    row = db.execute("SELECT * FROM application_kinds WHERE id=?", (kid,)).fetchone()
    if row is None:
        abort(404)
    return row

def _app(db, aid):
    row = db.execute("SELECT * FROM applications WHERE id=?", (aid,)).fetchone()
    if row is None or row["deleted_at"]:
        abort(404)
    return row

def _can_delete(db, user, app):
    """Who can delete an application (it goes to the Recycle Bin, it is not
    erased at once): ONLY the owner, an administrative permission user and
    the portal admin. The checker, the HR approver and the HR & Admin
    department admin CANNOT delete it."""
    if is_portal_admin(user):
        return True
    if app["owner_id"] == user["id"]:
        return True
    return False

def _is_hr_dept_admin(db, user):
    """A department admin of the HR & Admin department."""
    did = hr_admin_dept_id(db)
    return bool(user and user["is_dept_admin"] and did and user["department_id"] == did)

def _can_view(db, user, app):
    if is_portal_admin(user):
        return True
    if app["owner_id"] == user["id"]:
        return True
    if app["recipient_id"] == user["id"]:
        return True
    # Every user in the same department can see that department's applications
    # (they appear in that department's All applications sub-tab).
    if user["department_id"] == app["department_id"]:
        return True
    # Any HR & Admin user can open and see every application (they all appear
    # in the All applications section), whatever department it came from.
    # Only the recipient and the HR dept admin can manage it.
    if user["department_id"] == hr_admin_dept_id(db):
        return True
    return False

def _can_edit(db, user, app):
    """The owner (only while Pending), the checker (while Pending), the HR
    approver (while Checked) and the HR & Admin department admin can edit
    the application. Nobody else can."""
    if _is_hr_dept_admin(db, user):
        return True
    if app["owner_id"] == user["id"] and app["status"] == "pending":
        return True
    if app["checker_id"] == user["id"] and app["status"] == "pending":
        return True
    if app["approver_id"] == user["id"] and app["status"] == "checked":
        return True
    return False

def _can_check(db, user, app):
    """The checker (the own-department person the application was sent to)
    while it is still Pending. They upload their signature under Checked By
    and forward it to an HR & Admin user."""
    return app["checker_id"] == user["id"] and app["status"] == "pending"

def _can_manage(db, user, app):
    """The HR approver (the HR & Admin user it was forwarded to) and the HR
    & Admin department admin change the status, set the HR note and upload
    the Approved By signature — only once the checker has forwarded it
    (status 'checked')."""
    if app["status"] != "checked":
        return False
    return app["approver_id"] == user["id"] or _is_hr_dept_admin(db, user)

def _can_manage_public(db, user, app):
    return (is_portal_admin(user) or app["owner_id"] == user["id"] or app["recipient_id"] == user["id"]
            or (_is_dept_admin(user) and app["department_id"] == user["department_id"]))

def _own_dept_users(db, dept_id):
    """Active, approved users in a department — the only people an
    application can be sent to for checking. Department admins first."""
    return db.execute("SELECT id, full_name, designation, is_dept_admin FROM users "
                      "WHERE department_id=? AND is_active=1 AND is_deleted=0 AND approval_status='approved' "
                      "ORDER BY is_dept_admin DESC, full_name",
                      (dept_id,)).fetchall()

def _app_history(db, aid):
    return db.execute("SELECT * FROM application_history WHERE application_id=? ORDER BY id DESC LIMIT 100", (aid,)).fetchall()

def _log_history(db, aid, user, action, field="", old_value="", new_value=""):
    db.execute("INSERT INTO application_history(application_id,user_id,username,full_name,action,field,old_value,new_value) VALUES (?,?,?,?,?,?,?,?)",
               (aid, user["id"], user["username"], user["full_name"], action, field, old_value, new_value))

def _new_application_code(db):
    for _ in range(200):
        cand = f"HRC-{secrets.randbelow(90000) + 10000}"
        if db.execute("SELECT 1 FROM applications WHERE public_code=?", (cand,)).fetchone() is None:
            if db.execute("SELECT 1 FROM invoices WHERE public_code=?", (cand,)).fetchone() is None:
                if db.execute("SELECT 1 FROM item_requests WHERE public_code=?", (cand,)).fetchone() is None:
                    if db.execute("SELECT 1 FROM public_links WHERE code_text=?", (cand,)).fetchone() is None:
                        if db.execute("SELECT 1 FROM ddb_rows WHERE public_code=?", (cand,)).fetchone() is None:
                            return cand
    return None

def _long_date(iso):
    """YYYY-MM-DD -> '16 November 2026' for the formal letter."""
    try:
        y, m, d = [int(p) for p in (iso or "").split("-")]
        return f"{d} {_MONTHS[m - 1]} {y}"
    except Exception:
        return iso or ""

def _days_between(from_iso, to_iso):
    try:
        f = datetime.strptime(from_iso, "%Y-%m-%d").date()
        t = datetime.strptime(to_iso, "%Y-%m-%d").date()
        return (t - f).days + 1
    except Exception:
        return 0

def _default_body(kind_name, from_iso, to_iso, days, reason):
    """The standard letter body, pre-filled on the form and editable by the
    applicant. Paragraphs are separated by a blank line."""
    noun = (kind_name or "leave").strip().lower()
    day_word = "day" if days == 1 else "days"
    first = (f"I am writing to request {noun} for {days} {day_word}, from {_long_date(from_iso)} "
             f"to {_long_date(to_iso)}, for {reason.strip()}. I have handed over my pending work "
             "to my colleague, and I will be reachable on my phone during the leave.")
    return first + "\n\nI would be grateful if you would kindly approve my leave."

def _qr_svg(url):
    return segno.make(url, error="m").svg_inline(scale=4, border=1, dark="#10283a", omitsize=True)

def _trim_signature_image(path):
    """Crop an uploaded signature picture to the ink, with the same small
    margin on every side, so the ink sits centred in the picture. A
    signature photo or scan often has more blank space on one side than
    the other; without this, the picture is centred in its block but the
    writing (and any line under it) sits left of the title below it.
    Handles transparent PNGs and white-background pictures alike. Only
    rewrites the file when the crop actually removes blank space, and
    leaves the file alone when the picture cannot be read (Pillow is
    only an indirect dependency, via reportlab)."""
    try:
        from PIL import Image, ImageChops
    except Exception:
        return
    try:
        im = Image.open(path)
    except Exception:
        return
    try:
        rgba = im.convert("RGBA")
        opaque = rgba.split()[3].point(lambda v: 255 if v > 30 else 0)
        dark = rgba.convert("L").point(lambda v: 255 if v < 235 else 0)
        ink = ImageChops.multiply(opaque, dark)
        box = ink.getbbox()
        if not box:
            return
        m = 8
        crop = (max(0, box[0] - m), max(0, box[1] - m),
                min(rgba.size[0], box[2] + m), min(rgba.size[1], box[3] + m))
        if crop == (0, 0, rgba.size[0], rgba.size[1]):
            return
        cropped = rgba.crop(crop)
        fmt = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}.get(
            path.rsplit(".", 1)[-1].lower(), "PNG")
        if fmt == "JPEG":
            cropped.convert("RGB").save(path, fmt, quality=92)
        else:
            cropped.save(path, fmt)
    except Exception:
        return

def _save_signature(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in SIG_EXTENSIONS:
        return None
    folder = os.path.join(config.UPLOAD_DIR, "app_signatures")
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(10) + "." + ext
    path = os.path.join(folder, name)
    file_storage.save(path)
    _trim_signature_image(path)
    return name

def _signature_path(name):
    if not name:
        return None
    p = os.path.join(config.UPLOAD_DIR, "app_signatures", name)
    return p if os.path.exists(p) else None

def _notify_dept_admins(db, app, text, link):
    """The application's department admins are told, except the owner (the
    owner is already told in the same action)."""
    _admins = [r[0] for r in db.execute(
        "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1",
        (app["department_id"],))]
    notify(db, [uid for uid in _admins if uid != app["owner_id"]], text, link, skip=g.user["id"])

# ---------------------------------------------------------------- the page (inside More)
@bp.route("/applications")
@login_required
def list_applications():
    db = get_db()
    tab = (request.args.get("apptab") or "my").strip()
    if tab not in ("my", "all", "received"):
        tab = "my"
    is_hr = bool(hr_admin_dept_id(db)) and g.user["department_id"] == hr_admin_dept_id(db)
    # The Received tab is for anyone an application was sent to: the HR
    # approver (once it is Checked) and the own-department checker (while
    # it is Pending). HR users always see it; anyone else sees it when
    # something was sent to them.
    has_received = db.execute("SELECT 1 FROM applications WHERE recipient_id=? AND deleted_at IS NULL LIMIT 1", (g.user["id"],)).fetchone() is not None
    show_received = bool(is_hr or has_received)
    if tab == "received" and not show_received:
        tab = "all"
    kinds = db.execute("SELECT * FROM application_kinds WHERE department_id=? AND status='active' ORDER BY id",
                       (g.user["department_id"],)).fetchall()
    # KPI counts for the current user (deleted applications are in the Recycle Bin, not here).
    counts = {"my": 0, "pending": 0, "checked": 0, "approved": 0, "rejected": 0}
    for r in db.execute("SELECT status, COUNT(*) c FROM applications WHERE owner_id=? AND deleted_at IS NULL GROUP BY status", (g.user["id"],)):
        counts["my"] += r["c"]
        counts[r["status"]] = counts.get(r["status"], 0) + r["c"]
    # The list.
    can_all = can_see_all_departments(db, g.user)
    fdept = request.args.get("fdept", type=int)
    fstatus = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()
    where = ["a.deleted_at IS NULL"]
    params = []
    if tab == "my":
        where.append("a.owner_id=?"); params.append(g.user["id"])
    elif tab == "received":
        where.append("a.recipient_id=?"); params.append(g.user["id"])
    else:
        if not can_all:
            where.append("a.department_id=?"); params.append(g.user["department_id"])
        elif fdept:
            where.append("a.department_id=?"); params.append(fdept)
    if fstatus in STATUSES:
        where.append("a.status=?"); params.append(fstatus)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(a.number LIKE ? ESCAPE '\\' OR k.name LIKE ? ESCAPE '\\' OR o.full_name LIKE ? ESCAPE '\\' "
                     "OR r.full_name LIKE ? ESCAPE '\\' OR d.name LIKE ? ESCAPE '\\')")
        params += [like, like, like, like, like]
    sql = ("SELECT a.*, k.name AS kind_name, o.full_name AS owner_name, r.full_name AS recipient_name, "
           "d.name AS dept_name FROM applications a LEFT JOIN application_kinds k ON k.id=a.kind_id "
           "LEFT JOIN users o ON o.id=a.owner_id LEFT JOIN users r ON r.id=a.recipient_id "
           "LEFT JOIN departments d ON d.id=a.department_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY a.id DESC"
    rows = db.execute(sql, params).fetchall()
    depts = db.execute("SELECT id, name FROM departments ORDER BY name").fetchall() if can_all else []
    return render_template("application_list.html", kinds=kinds, rows=rows, tab=tab, counts=counts,
                           can_all=can_all, depts=depts, fdept=fdept, fstatus=fstatus, q=q,
                           is_hr=is_hr, show_received=show_received, statuses=STATUSES, labels=STATUS_LABELS)

# ---------------------------------------------------------------- kinds (dept admin)
@bp.route("/applications/kinds")
@login_required
def kinds():
    _dept_admin_required()
    db = get_db()
    rows = db.execute("SELECT * FROM application_kinds WHERE department_id=? ORDER BY id", (g.user["department_id"],)).fetchall()
    return render_template("application_kinds.html", rows=rows)

@bp.route("/applications/kinds/starters", methods=["POST"])
@login_required
def kind_starters():
    _dept_admin_required()
    db = get_db()
    starters = [("Annual Leave", "AL"), ("Sick Leave", "SL"), ("Casual Leave", "CL")]
    for name, prefix in starters:
        if db.execute("SELECT 1 FROM application_kinds WHERE department_id=? AND name=?", (g.user["department_id"], name)).fetchone() is None:
            db.execute("INSERT INTO application_kinds(department_id,created_by,name,number_prefix,status) VALUES (?,?,?,?,?)",
                       (g.user["department_id"], g.user["id"], name, prefix, "active"))
    log(db, "application_kind_starters", "Annual/Sick/Casual Leave")
    db.commit(); flash("Starter application kinds created for your department.", "ok")
    return redirect(url_for("applications.kinds"))

@bp.route("/applications/kinds/new", methods=["GET", "POST"])
@login_required
def kind_new():
    _dept_admin_required()
    db = get_db()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        prefix = (request.form.get("number_prefix") or "LV").strip().upper()[:10]
        company_name = (request.form.get("company_name") or "").strip()
        company_address = (request.form.get("company_address") or "").strip()
        if not name:
            flash("Write a kind name.", "error")
            return render_template("application_kind_form.html", kind=None)
        db.execute("INSERT INTO application_kinds(department_id,created_by,name,number_prefix,company_name,company_address,status) VALUES (?,?,?,?,?,?,?)",
                   (g.user["department_id"], g.user["id"], name, prefix, company_name, company_address, "active"))
        log(db, "application_kind_new", name)
        db.commit(); flash("Application kind saved.", "ok")
        return redirect(url_for("applications.kinds"))
    return render_template("application_kind_form.html", kind=None)

@bp.route("/applications/kinds/<int:kid>/edit", methods=["GET", "POST"])
@login_required
def kind_edit(kid):
    _dept_admin_required()
    db = get_db(); kind = _kind(db, kid)
    if kind["department_id"] != g.user["department_id"]:
        abort(403)
    if request.method == "POST":
        name = (request.form.get("name") or kind["name"]).strip()
        prefix = (request.form.get("number_prefix") or kind["number_prefix"]).strip().upper()[:10]
        company_name = (request.form.get("company_name") or "").strip()
        company_address = (request.form.get("company_address") or "").strip()
        status = "active" if request.form.get("status") != "draft" else "draft"
        db.execute("UPDATE application_kinds SET name=?,number_prefix=?,company_name=?,company_address=?,status=?,updated_at=datetime('now','localtime') WHERE id=?",
                   (name, prefix, company_name, company_address, status, kid))
        log(db, "application_kind_edit", name)
        db.commit(); flash("Application kind saved. Changes apply to new applications only.", "ok")
        return redirect(url_for("applications.kinds"))
    return render_template("application_kind_form.html", kind=kind)

# ---------------------------------------------------------------- create an application
@bp.route("/applications/new", methods=["GET", "POST"])
@login_required
def application_new():
    db = get_db()
    kind_id = request.values.get("kind", type=int)
    kind = _kind(db, kind_id) if kind_id else None
    if kind is not None and (kind["department_id"] != g.user["department_id"] or kind["status"] != "active"):
        flash("That application kind is not available to you.", "error")
        return redirect(url_for("applications.list_applications"))
    recipients = _own_dept_users(db, g.user["department_id"])
    if request.method == "POST" and kind is not None:
        # The recipient must be a user in the applicant's OWN department —
        # a department user or the person with Department admin permission.
        # That person checks it, signs it, and forwards it to HR & Admin.
        try:
            recipient_id = int(request.form.get("recipient_id") or 0)
        except ValueError:
            recipient_id = 0
        from_date = (request.form.get("from_date") or "").strip()
        to_date = (request.form.get("to_date") or "").strip()
        reason = (request.form.get("reason") or "").strip()
        body = (request.form.get("letter_body") or "").strip()
        days = _days_between(from_date, to_date)
        error = None
        if recipient_id not in [r["id"] for r in recipients]:
            error = "Choose a recipient from your own department."
        elif not from_date or not to_date or days < 1:
            error = "Choose a from date and a to date, with the to date on or after the from date."
        elif not reason:
            error = "Write a reason for the leave."
        elif not body:
            error = "Write the letter."
        if error:
            flash(error, "error")
        else:
            number = f"{kind['number_prefix']}-{kind['next_number']:04d}"
            db.execute("UPDATE application_kinds SET next_number=next_number+1 WHERE id=?", (kind["id"],))
            aid = db.execute("INSERT INTO applications(department_id,kind_id,owner_id,recipient_id,checker_id,number,status,from_date,to_date,days,reason,letter_body) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (g.user["department_id"], kind["id"], g.user["id"], recipient_id, recipient_id, number, "pending",
                              from_date, to_date, days, reason, body)).lastrowid
            _log_history(db, aid, g.user, "created", "", "", number)
            rec = db.execute("SELECT full_name FROM users WHERE id=?", (recipient_id,)).fetchone()
            log(db, "application_new", number)
            notify(db, [recipient_id],
                   f"{g.user['full_name']} sent you a {kind['name']} application {number} to check.",
                   url_for("applications.detail", aid=aid), skip=g.user["id"])
            _dept = db.execute("SELECT * FROM departments WHERE id=?", (g.user["department_id"],)).fetchone()
            notify_ddb_task(db, g.user, _dept,
                            f"{g.user['full_name']} sent a {kind['name']} application {number} to {rec['full_name'] if rec else 'their department'} to check.",
                            url_for("applications.detail", aid=aid))
            db.commit()
            flash(f"Application {number} sent to {rec['full_name'] if rec else 'your department'} to check.", "ok")
            return redirect(url_for("applications.detail", aid=aid))
    return render_template("application_form.html", kind=kind, recipients=recipients)

# ---------------------------------------------------------------- edit an application
@bp.route("/applications/<int:aid>/edit", methods=["GET", "POST"])
@login_required
def application_edit(aid):
    """Edit an application. The owner (only while Pending), the recipient
    and the HR & Admin dept admin can edit it. The number, the kind and the
    recipient stay the same — only the from/to dates, the reason and the
    letter body can change. Saving writes one edit-log entry per changed
    field, logs the edit, and notifies the other party."""
    db = get_db(); app = _app(db, aid)
    if not _can_edit(db, g.user, app):
        abort(403)
    kind = _kind(db, app["kind_id"]) if app["kind_id"] else None
    owner = db.execute("SELECT full_name FROM users WHERE id=?", (app["owner_id"],)).fetchone()
    recipient = db.execute("SELECT full_name FROM users WHERE id=?", (app["recipient_id"],)).fetchone() if app["recipient_id"] else None
    if request.method == "POST":
        from_date = (request.form.get("from_date") or "").strip()
        to_date = (request.form.get("to_date") or "").strip()
        reason = (request.form.get("reason") or "").strip()
        body = (request.form.get("letter_body") or "").strip()
        days = _days_between(from_date, to_date)
        error = None
        if not from_date or not to_date or days < 1:
            error = "Choose a from date and a to date, with the to date on or after the from date."
        elif not reason:
            error = "Write a reason for the leave."
        elif not body:
            error = "Write the letter."
        if error:
            flash(error, "error")
            return render_template("application_edit_form.html", app=app, kind=kind,
                                   owner_name=owner["full_name"] if owner else "",
                                   recipient_name=recipient["full_name"] if recipient else "")
        if (app["from_date"] or "") != from_date:
            _log_history(db, aid, g.user, "edit", "From date", app["from_date"] or "", from_date)
        if (app["to_date"] or "") != to_date:
            _log_history(db, aid, g.user, "edit", "To date", app["to_date"] or "", to_date)
        if (app["days"] or 0) != days:
            _log_history(db, aid, g.user, "edit", "Days", str(app["days"]), str(days))
        if (app["reason"] or "") != reason:
            _log_history(db, aid, g.user, "edit", "Reason", app["reason"] or "", reason)
        if (app["letter_body"] or "") != body:
            _log_history(db, aid, g.user, "edit", "Letter", app["letter_body"] or "", body)
        db.execute("UPDATE applications SET from_date=?,to_date=?,days=?,reason=?,letter_body=?,updated_at=datetime('now','localtime') WHERE id=?",
                   (from_date, to_date, days, reason, body, aid))
        log(db, "application_edit", app["number"])
        if g.user["id"] == app["owner_id"]:
            notify(db, [app["recipient_id"]],
                   f"{g.user['full_name']} updated the {kind['name'] if kind else 'leave'} application {app['number']} sent to you.",
                   url_for("applications.detail", aid=aid), skip=g.user["id"])
        else:
            notify(db, [app["owner_id"]],
                   f"{g.user['full_name']} updated your {kind['name'] if kind else 'leave'} application {app['number']}.",
                   url_for("applications.detail", aid=aid), skip=g.user["id"])
        _notify_dept_admins(db, app, f"{g.user['full_name']} updated the application {app['number']}.",
                            url_for("applications.detail", aid=aid))
        db.commit()
        flash(f"Application {app['number']} updated. The other party has been notified.", "ok")
        return redirect(url_for("applications.detail", aid=aid))
    return render_template("application_edit_form.html", app=app, kind=kind,
                           owner_name=owner["full_name"] if owner else "",
                           recipient_name=recipient["full_name"] if recipient else "")

# ---------------------------------------------------------------- detail, status, note, signature, PDF, public QR
@bp.route("/applications/<int:aid>")
@login_required
def detail(aid):
    db = get_db(); app = _app(db, aid)
    if not _can_view(db, g.user, app):
        abort(403)
    kind = _kind(db, app["kind_id"]) if app["kind_id"] else None
    owner = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["owner_id"],)).fetchone()
    recipient = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["recipient_id"],)).fetchone() if app["recipient_id"] else None
    checker = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["checker_id"],)).fetchone() if app["checker_id"] else None
    approver = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["approver_id"],)).fetchone() if app["approver_id"] else None
    dept = db.execute("SELECT name FROM departments WHERE id=?", (app["department_id"],)).fetchone()
    signer = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["signature_by"],)).fetchone() if app["signature_by"] else None
    qr_svg = qr_url = None
    if app["public_code"] and app["public_enabled"]:
        qr_url = external_url(db, "applications.code_page", code=app["public_code"])
        qr_svg = _qr_svg(qr_url)
    return render_template("application_detail.html", app=app, kind=kind,
                           owner=owner, recipient=recipient, checker=checker, approver=approver,
                           dept=dept, signer=signer,
                           qr_svg=qr_svg, qr_url=qr_url,
                           can_manage=_can_manage(db, g.user, app),
                           can_edit=_can_edit(db, g.user, app),
                           can_delete=_can_delete(db, g.user, app),
                           can_check=_can_check(db, g.user, app),
                           can_manage_public=_can_manage_public(db, g.user, app),
                           hr_users=hr_admin_users(db),
                           history=_app_history(db, aid),
                           statuses=STATUSES, labels=STATUS_LABELS)

@bp.route("/applications/<int:aid>/delete", methods=["POST"])
@login_required
def application_delete(aid):
    """Delete an application. It is a soft delete: the application goes to
    the Recycle Bin for 30 days, where it can be restored, and is only
    erased for good from there. Its number is never reused. Deleting asks
    for the user's own password first (the same re-auth as Delete invoice);
    a wrong password deletes nothing. Only the owner, an administrative
    permission user and the portal admin can delete it."""
    db = get_db(); app = _app(db, aid)
    if not _can_delete(db, g.user, app):
        abort(403)
    from security import reauth_ok
    if not reauth_ok(g.user, request.form):
        flash("Your password is not correct. Nothing was deleted.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    db.execute("UPDATE applications SET deleted_at=datetime('now','localtime'), deleted_by=?,"
               "updated_at=datetime('now','localtime') WHERE id=?", (g.user["id"], aid))
    _log_history(db, aid, g.user, "deleted", "Application", app["number"], "deleted")
    log(db, "application_deleted", app["number"])
    # Tell the other party: the owner if someone else deleted it, the
    # checker / approver if the owner deleted it.
    other = app["recipient_id"] if g.user["id"] == app["owner_id"] else app["owner_id"]
    if other and other != g.user["id"]:
        notify(db, [other],
               f"{g.user['full_name']} deleted the application {app['number']}. It is in the Recycle Bin for 30 days.",
               url_for("applications.list_applications"), skip=g.user["id"])
    db.commit()
    flash(f"Application {app['number']} deleted. It is in the Recycle bin for {config.BIN_DAYS} days — it can be restored from there.", "ok")
    return redirect(url_for("applications.list_applications"))

# ---------------------------------------------------------------- check and forward (the checker)
@bp.route("/applications/<int:aid>/check-signature", methods=["POST"])
@login_required
def check_signature(aid):
    """The checker uploads their signature image (it appears above
    'Checked By', with their name and designation under it). The checker
    must have uploaded a signature before they can forward the application
    to HR."""
    db = get_db(); app = _app(db, aid)
    if not _can_check(db, g.user, app):
        abort(403)
    name = _save_signature(request.files.get("signature"))
    if not name:
        flash("Upload a signature image (png, jpg, jpeg or webp).", "error")
        return redirect(url_for("applications.detail", aid=aid))
    if app["checker_signature_path"]:
        try:
            old = os.path.join(config.UPLOAD_DIR, "app_signatures", os.path.basename(app["checker_signature_path"]))
            if os.path.exists(old):
                os.remove(old)
        except Exception:
            pass
    db.execute("UPDATE applications SET checker_signature_path=?,checker_signature_at=datetime('now','localtime'),updated_at=datetime('now','localtime') WHERE id=?",
               (name, aid))
    _log_history(db, aid, g.user, "edit", "Checker signature", "", g.user["full_name"])
    log(db, "application_checked_signature", app["number"])
    db.commit()
    flash("Your signature has been added under Checked By. You can now forward the application to HR & Admin.", "ok")
    return redirect(url_for("applications.detail", aid=aid))

@bp.route("/applications/<int:aid>/forward", methods=["POST"])
@login_required
def forward_to_hr(aid):
    """The checker forwards the application to ONE specific HR & Admin user.
    The checker must have uploaded their signature first. Forwarding sets
    the status to Checked, makes the HR user the person it is currently
    with (recipient and approver), and notifies the HR user and the owner."""
    db = get_db(); app = _app(db, aid)
    if not _can_check(db, g.user, app):
        abort(403)
    if not app["checker_signature_path"]:
        flash("Upload your signature first — you can only forward the application once your signature is under Checked By.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    try:
        hr_id = int(request.form.get("hr_user_id") or 0)
    except ValueError:
        hr_id = 0
    hr_users = hr_admin_users(db)
    if hr_id not in [r["id"] for r in hr_users]:
        flash("Choose an HR & Admin user to forward it to.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    db.execute("UPDATE applications SET recipient_id=?,approver_id=?,status='checked',updated_at=datetime('now','localtime') WHERE id=?",
               (hr_id, hr_id, aid))
    _log_history(db, aid, g.user, "status", "Status", STATUS_LABELS["pending"], STATUS_LABELS["checked"])
    log(db, "application_forwarded", f"{app['number']} -> HR user {hr_id}")
    hr = db.execute("SELECT full_name FROM users WHERE id=?", (hr_id,)).fetchone()
    notify(db, [hr_id],
           f"{g.user['full_name']} checked the application {app['number']} and forwarded it to you for approval.",
           url_for("applications.detail", aid=aid), skip=g.user["id"])
    notify(db, [app["owner_id"]],
           f"{g.user['full_name']} checked your application {app['number']} and forwarded it to {hr['full_name'] if hr else 'HR & Admin'}.",
           url_for("applications.detail", aid=aid), skip=g.user["id"])
    db.commit()
    flash(f"Application {app['number']} forwarded to {hr['full_name'] if hr else 'HR & Admin'}. It is now Checked.", "ok")
    return redirect(url_for("applications.detail", aid=aid))

@bp.route("/applications/<int:aid>/status", methods=["POST"])
@login_required
def change_status(aid):
    """The HR approver (or the HR & Admin dept admin) approves or rejects
    the application, once the checker has forwarded it (status Checked).
    The checker and the owner are both told."""
    db = get_db(); app = _app(db, aid)
    if not _can_manage(db, g.user, app):
        abort(403)
    new_status = (request.form.get("status") or "").strip()
    if new_status not in ("approved", "rejected"):
        flash("Choose a status: Approved or Rejected.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    if new_status == app["status"]:
        flash("Status is already " + STATUS_LABELS[new_status] + ".", "ok")
        return redirect(url_for("applications.detail", aid=aid))
    db.execute("UPDATE applications SET status=?,updated_at=datetime('now','localtime') WHERE id=?", (new_status, aid))
    _log_history(db, aid, g.user, "status", "Status", STATUS_LABELS.get(app["status"], app["status"]), STATUS_LABELS[new_status])
    log(db, "application_status", f"{app['number']} -> {new_status}")
    notify(db, [app["owner_id"]],
           f"{g.user['full_name']} changed your application {app['number']} to {STATUS_LABELS[new_status]}.",
           url_for("applications.detail", aid=aid), skip=g.user["id"])
    if app["checker_id"] and app["checker_id"] != app["owner_id"]:
        notify(db, [app["checker_id"]],
               f"{g.user['full_name']} changed the application {app['number']} you checked to {STATUS_LABELS[new_status]}.",
               url_for("applications.detail", aid=aid), skip=g.user["id"])
    _notify_dept_admins(db, app, f"{g.user['full_name']} changed the application {app['number']} to {STATUS_LABELS[new_status]}.",
                        url_for("applications.detail", aid=aid))
    db.commit()
    flash(f"Status changed to {STATUS_LABELS[new_status]}. The applicant and the checker have been notified.", "ok")
    return redirect(url_for("applications.detail", aid=aid))

@bp.route("/applications/<int:aid>/note", methods=["POST"])
@login_required
def set_note(aid):
    db = get_db(); app = _app(db, aid)
    if not _can_manage(db, g.user, app):
        abort(403)
    note = (request.form.get("hr_note") or "").strip()
    db.execute("UPDATE applications SET hr_note=?,updated_at=datetime('now','localtime') WHERE id=?", (note, aid))
    if (app["hr_note"] or "") != note:
        _log_history(db, aid, g.user, "edit", "HR note", app["hr_note"] or "", note)
    log(db, "application_note", app["number"])
    db.commit()
    flash("HR note saved.", "ok")
    return redirect(url_for("applications.detail", aid=aid))

@bp.route("/applications/<int:aid>/signature", methods=["POST"])
@login_required
def upload_signature(aid):
    db = get_db(); app = _app(db, aid)
    if not _can_manage(db, g.user, app):
        abort(403)
    name = _save_signature(request.files.get("signature"))
    if not name:
        flash("Upload a signature image (png, jpg, jpeg or webp).", "error")
        return redirect(url_for("applications.detail", aid=aid))
    # The old signature image is replaced, so remove it.
    if app["signature_path"]:
        try:
            old = os.path.join(config.UPLOAD_DIR, "app_signatures", os.path.basename(app["signature_path"]))
            if os.path.exists(old):
                os.remove(old)
        except Exception:
            pass
    db.execute("UPDATE applications SET signature_path=?,signature_by=?,signature_at=datetime('now','localtime'),updated_at=datetime('now','localtime') WHERE id=?",
               (name, g.user["id"], aid))
    _log_history(db, aid, g.user, "edit", "Signature", "", g.user["full_name"])
    log(db, "application_signature", app["number"])
    db.commit()
    flash("Your signature has been added to the application.", "ok")
    return redirect(url_for("applications.detail", aid=aid))

@bp.route("/applications/<int:aid>/signature/<kind>")
@login_required
def signature_image(aid, kind):
    """Serve a signature image inline for the detail page letter preview.
    kind is 'checker' or 'approver'. Only users who can view the
    application can see it."""
    from flask import send_file
    db = get_db(); app = _app(db, aid)
    if not _can_view(db, g.user, app):
        abort(403)
    if kind == "checker":
        name = app["checker_signature_path"]
    elif kind == "approver":
        name = app["signature_path"]
    else:
        abort(404)
    path = _signature_path(name)
    if not path:
        abort(404)
    return send_file(path)

@bp.route("/applications/code/<code>/signature/<kind>")
def code_signature_image(code, kind):
    """Serve a signature image inline for the public code page letter
    preview. Public, like the code PDF — only when the application's
    public QR is on and it is not deleted."""
    from flask import send_file
    db = get_db()
    app = db.execute("SELECT * FROM applications WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if app is None or app["deleted_at"] or not _public_check(db, app):
        abort(404)
    if kind == "checker":
        name = app["checker_signature_path"]
    elif kind == "approver":
        name = app["signature_path"]
    else:
        abort(404)
    path = _signature_path(name)
    if not path:
        abort(404)
    return send_file(path)

@bp.route("/applications/<int:aid>/pdf")
@login_required
def application_pdf(aid):
    db = get_db(); app = _app(db, aid)
    if not _can_view(db, g.user, app):
        abort(403)
    data = _build_pdf(db, app)
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{(app["number"] or "application")}.pdf"'
    return resp

@bp.route("/applications/<int:aid>/public", methods=["POST"])
@login_required
def application_public(aid):
    db = get_db(); app = _app(db, aid)
    if not _can_manage_public(db, g.user, app):
        abort(403)
    action = request.form.get("action", "save")
    if action == "off":
        db.execute("UPDATE applications SET public_enabled=0 WHERE id=?", (aid,))
    elif action == "regenerate":
        # new code kills the old printed QR
        db.execute("UPDATE applications SET public_code=?,public_enabled=1 WHERE id=?", (_new_application_code(db), aid))
    else:
        code = app["public_code"] or _new_application_code(db)
        db.execute("UPDATE applications SET public_code=?,public_enabled=1 WHERE id=?", (code, aid))
    db.commit(); flash("Public QR saved.", "ok"); return redirect(url_for("applications.detail", aid=aid))

@bp.route("/applications/<int:aid>/qr")
@login_required
def application_qr(aid):
    db = get_db(); app = _app(db, aid)
    if not _can_view(db, g.user, app) or not app["public_code"]:
        abort(404)
    url = external_url(db, "applications.code_page", code=app["public_code"])
    item = {"id": app["id"], "title": "Application Letter", "dept": app["number"] or "", "svg": _qr_svg(url), "url": url, "code": app["public_code"]}
    return render_template("qr_label.html", items=[item], many=False)

def _public_check(db, app):
    return app is not None and bool(app["public_enabled"])

@bp.route("/applications/code/<code>")
def code_page(code):
    """Public code view: anyone who scans the QR (or types HRC-#####) sees the application letter and downloads the PDF. No login needed."""
    db = get_db()
    app = db.execute("SELECT * FROM applications WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if app is None or app["deleted_at"]:
        return render_template("application_code.html", code=code, status="missing", app=None), 404
    if not _public_check(db, app):
        return render_template("application_code.html", code=code, status="off", app=app), 410
    db.execute("UPDATE applications SET public_views=public_views+1 WHERE id=?", (app["id"],)); db.commit()
    kind = _kind(db, app["kind_id"]) if app["kind_id"] else None
    owner = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["owner_id"],)).fetchone()
    recipient = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["recipient_id"],)).fetchone() if app["recipient_id"] else None
    checker = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["checker_id"],)).fetchone() if app["checker_id"] else None
    approver = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["approver_id"],)).fetchone() if app["approver_id"] else None
    dept = db.execute("SELECT name FROM departments WHERE id=?", (app["department_id"],)).fetchone()
    signer = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["signature_by"],)).fetchone() if app["signature_by"] else None
    return render_template("application_code.html", code=code, status="ok", app=app, kind=kind,
                           owner=owner, recipient=recipient, checker=checker, approver=approver,
                           dept=dept, signer=signer,
                           labels=STATUS_LABELS)

@bp.route("/applications/code/<code>/pdf")
def code_pdf(code):
    db = get_db()
    app = db.execute("SELECT * FROM applications WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if app is None or app["deleted_at"] or not _public_check(db, app):
        abort(404)
    data = _build_pdf(db, app)
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{code}.pdf"'
    return resp

def _build_pdf(db, app):
    kind = _kind(db, app["kind_id"]) if app["kind_id"] else None
    owner = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["owner_id"],)).fetchone()
    checker = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["checker_id"],)).fetchone() if app["checker_id"] else None
    recipient = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["recipient_id"],)).fetchone() if app["recipient_id"] else None
    dept = db.execute("SELECT name FROM departments WHERE id=?", (app["department_id"],)).fetchone()
    signer = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["signature_by"],)).fetchone() if app["signature_by"] else None
    approver = db.execute("SELECT full_name, designation FROM users WHERE id=?", (app["approver_id"],)).fetchone() if app["approver_id"] else None
    # The kind carries its own company name and address for the letterhead;
    # blank means the portal name and default address.
    company = (kind["company_name"] or "").strip() if kind else ""
    address = (kind["company_address"] or "").strip() if kind else ""
    if not company:
        company = setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME)
    if not address:
        address = config.DEFAULT_COMPANY_ADDRESS
    qr_url = external_url(db, "applications.code_page", code=app["public_code"]) if app["public_code"] else ""
    return exports.application_pdf(
        number=app["number"] or "", app_date=app["created_at"][:10] if app["created_at"] else "",
        kind_name=kind["name"] if kind else "", status=app["status"],
        status_label=STATUS_LABELS.get(app["status"], app["status"].title()),
        owner_name=owner["full_name"] if owner else "", owner_designation=owner["designation"] if owner else "",
        dept_name=dept["name"] if dept else "",
        checker_name=checker["full_name"] if checker else (recipient["full_name"] if recipient else ""),
        checker_designation=checker["designation"] if checker else "",
        checker_signature_path=_signature_path(app["checker_signature_path"]),
        recipient_name=recipient["full_name"] if recipient else "",
        from_date=app["from_date"] or "", to_date=app["to_date"] or "", days=app["days"] or 0,
        reason=app["reason"] or "", letter_body=app["letter_body"] or "", hr_note=app["hr_note"] or "",
        signer_name=(signer["full_name"] if signer else "") or (approver["full_name"] if approver else ""),
        signer_designation=(signer["designation"] if signer else "") or (approver["designation"] if approver else ""),
        signature_path=_signature_path(app["signature_path"]), signature_date=app["signature_at"][:10] if app["signature_at"] else "",
        code=app["public_code"] if app["public_enabled"] else "",
        company=company, company_address=address, qr_url=qr_url)
