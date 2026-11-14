"""
routes_applications.py - Application Letters (NEW in this version, section 60 in README).

A new page inside More, for all users EXCEPT the portal admin. A dept admin
makes an Application Letter kind for their OWN department (like an invoice
template / Item Request kind). A user picks a kind, fills in the leave
(from date, to date, reason, letter body) and sends the application through
an approval chain of up to three steps, which they pick on the creation
page. Each step has a role — Checked By, Approved By or Authorised By —
and a person from the applicant's own department, HR & Admin or
Management. A step can also be set to None, which skips it: two steps
means two signature blocks at the bottom of the letter, three means
three, one means one. The steps run strictly in order: the second person
cannot approve until the first has approved, and the third cannot approve
until the second has approved. Each person in the chain must tick "Use my
signature" (their saved signature from My settings) before they can
approve or reject. Each decision is only Approved or Rejected. The
application's status is Pending while the first step is waiting, Checked
while a later step is waiting, and Approved / Rejected once the last step
decides — or Rejected at once when any step rejects. The grey APPROVED
seal or REJECTED stamp appears on the PDF only once the LAST step has
approved or rejected it; an earlier rejection shows no seal or stamp.

A new application starts as Pending and gets a number like LV-0001
(sequential per kind). The owner can edit their own application while it
is still Pending.

The document is a formal application letter (not an invoice): a letterhead,
Ref + date, To (the lines the user wrote in the To box), Subject, the
body, the applicant's signature (name, designation, department, company),
and a FOR OFFICE USE section with the HR note and one signature block per
step — the step's saved signature image above their name and designation.
The owner's designation comes from their user account and is filled in
automatically. The kind carries its own company name and address for the
letterhead (blank = portal defaults). There is no separate Status or Date
line at the bottom of the letter.

The chain is stored in application_steps (one row per step, in order),
and the old columns on applications (recipient_id, checker_id,
approver_id, checker_signature_path, signature_path, signature_by,
signature_at) are kept in step with it, so the list, the Received tab,
the Recycle Bin and the old single-recipient create shape keep working.
Applications made before this build get their steps backfilled from
those columns (see models.init_db), and an application that was still
Pending with no approver keeps the old forward: its checker may still
forward it to an HR & Admin user, which adds the second step.

Sub-tabs on the page: My applications (only the current user's), All
applications, Received (only the applications currently with the current
user — the person whose turn it is in the chain). In All applications,
administrative permission users and HR & Admin users see ALL
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
from core import external_url, notify, notify_admin_task, notify_ddb_task, notify_dept_task, permission_user_ids, true_admin_ids
from models import get_db, log, setting_get
from routes_requests import hr_admin_dept_id, hr_admin_users, management_dept_id

bp = Blueprint("applications", __name__)
STATUSES = ["pending", "checked", "approved", "rejected"]
STATUS_LABELS = {"pending": "Pending", "checked": "Checked", "approved": "Approved", "rejected": "Rejected"}
# The three roles a step in the approval chain can have, and the verb used
# for that step in notifications ("sent you ... to check / approve /
# authorise"). The role dropdown on the creation page also offers None,
# which skips the step entirely.
STEP_ROLES = {"checked": "Checked By", "approved": "Approved By", "authorised": "Authorised By"}
STEP_VERBS = {"checked": "check", "approved": "approve", "authorised": "authorise"}
STEP_PAST = {"checked": "checked", "approved": "approved", "authorised": "authorised"}
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
    """Application Letters are for every user, including the portal admin
    (2026-11-14): the portal admin sees the list in the More menu and can
    see and delete every application. The public code pages (no login) are
    not affected. The portal admin may open the list, an application, delete
    it and download its PDF — but not create, check, forward, approve or
    manage kinds, which stay for the department users, the checker and HR."""
    if request.endpoint in ("applications.code_page", "applications.code_pdf"):
        return None
    if g.user is not None and is_true_admin(g.user):
        if request.endpoint in ("applications.list_applications", "applications.detail",
                                "applications.application_delete", "applications.application_pdf"):
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

def _steps(db, aid):
    """The approval chain for an application, in order, with each step's
    user's name, designation and department. A step whose user was
    purged has user_id None and no name — it still shows, with a blank
    name."""
    return db.execute("SELECT s.*, u.full_name, u.designation, d.name AS dept_name FROM application_steps s "
                      "LEFT JOIN users u ON u.id=s.user_id LEFT JOIN departments d ON d.id=u.department_id "
                      "WHERE s.application_id=? ORDER BY s.position",
                      (aid,)).fetchall()

def _current_step(db, aid):
    """The first step that has not decided yet — the person it is
    currently with. None once every step has decided."""
    for s in _steps(db, aid):
        if s["status"] == "pending":
            return s
    return None

def _step_user_ids(db, aid):
    return [s["user_id"] for s in _steps(db, aid) if s["user_id"]]

def _sync_app_from_steps(db, aid):
    """Keep the old columns on applications in step with the chain, so
    the list, the Received tab, the Recycle Bin and the old single-
    recipient create shape keep working: recipient_id is the person it
    is currently with (the last step's user once it is decided),
    checker_id is the Checked By step's user (or the first step's user
    when no step is Checked By), approver_id is the Approved By step's
    user (or NULL when there is none), checker_signature_path is the
    Checked By step's signature (or the first step's), and
    signature_path/by/at are the LAST step's signature once they have
    signed."""
    steps = _steps(db, aid)
    if not steps:
        return
    pending = [s for s in steps if s["status"] == "pending"]
    rejected = next((s for s in steps if s["status"] == "rejected"), None)
    if rejected:
        # The request goes no further once somebody rejects: the person
        # it is with is the one who rejected it, not the next person in
        # line (who never gets their turn).
        current = rejected
    elif pending:
        current = pending[0]
    else:
        current = steps[-1]
    checked = next((s for s in steps if s["role"] == "checked"), steps[0])
    approved = next((s for s in steps if s["role"] == "approved"), None)
    last = steps[-1]
    last_signed = last["signature_path"]
    db.execute("UPDATE applications SET recipient_id=?,checker_id=?,approver_id=?,"
               "checker_signature_path=?,checker_signature_at=?,"
               "signature_path=?,signature_by=?,signature_at=? WHERE id=?",
               (current["user_id"], checked["user_id"], approved["user_id"] if approved else None,
                checked["signature_path"], checked["signature_at"],
                last_signed, last["user_id"] if last_signed else None,
                last["signature_at"] if last_signed else None, aid))

def _adopt_mirrors(db, aid):
    """A signature stored on the application row itself (checker_signature_path
    or signature_path) before the chain existed still counts for its step:
    copy it into the matching step when that step has no signature yet.
    The step rows are the source of truth from here on; the mirrors are
    kept in step by _sync_app_from_steps."""
    app = db.execute("SELECT * FROM applications WHERE id=?", (aid,)).fetchone()
    if app is None:
        return
    steps = _steps(db, aid)
    for s in steps:
        if s["signature_path"]:
            continue
        if s["role"] == "checked" and app["checker_signature_path"]:
            db.execute("UPDATE application_steps SET signature_path=?,signature_at=? WHERE id=?",
                       (app["checker_signature_path"], app["checker_signature_at"], s["id"]))
        elif s["position"] == len(steps) and app["signature_path"]:
            db.execute("UPDATE application_steps SET signature_path=?,signature_at=? WHERE id=?",
                       (app["signature_path"], app["signature_at"], s["id"]))

def _can_view(db, user, app):
    if is_portal_admin(user):
        return True
    if app["owner_id"] == user["id"]:
        return True
    if app["recipient_id"] == user["id"]:
        return True
    # Anyone in the chain can open it — a later step's user needs to see
    # it to know they are waiting for the current step's approval.
    if user["id"] in _step_user_ids(db, app["id"]):
        return True
    # A department admin can open his department's applications (they
    # appear in his All applications tab).
    if _is_dept_admin(user) and app["department_id"] == user["department_id"]:
        return True
    # The HR & Admin department admin can also open any application
    # sent to one of his department's users (they appear in his All
    # applications tab too). A regular user in the same department as
    # the applicant cannot open another user's application.
    if _is_hr_dept_admin(db, user):
        hr = hr_admin_dept_id(db)
        if hr:
            row = db.execute("SELECT 1 FROM application_steps s JOIN users u ON u.id=s.user_id "
                             "WHERE s.application_id=? AND u.department_id=? LIMIT 1",
                             (app["id"], hr)).fetchone()
            if row:
                return True
    return False

def _can_edit(db, user, app):
    """The owner (only while Pending), the person whose turn it is in the
    chain, and the HR & Admin department admin can edit the application.
    Nobody else can. (The old rules — checker while Pending, approver
    while Checked — are the same thing for a two-step chain.)"""
    if _is_hr_dept_admin(db, user):
        return True
    if app["owner_id"] == user["id"] and app["status"] == "pending":
        return True
    cur = _current_step(db, app["id"])
    if cur and cur["user_id"] == user["id"] and app["status"] in ("pending", "checked"):
        return True
    return False

def _can_act(db, user, app):
    """It is this user's turn in the chain: they are the first step that
    has not decided yet, and the application is still undecided. Only
    they can tick "Use my signature" and approve or reject it — the next
    person cannot act until they have approved."""
    if app["status"] not in ("pending", "checked"):
        return False
    cur = _current_step(db, app["id"])
    return bool(cur) and cur["user_id"] == user["id"]

def _can_check(db, user, app):
    """Kept for the old name: the person whose turn it is, when that turn
    is the first step (the checker)."""
    cur = _current_step(db, app["id"])
    return _can_act(db, user, app) and bool(cur) and cur["position"] == 1

def _can_manage(db, user, app):
    """Kept for the old name: the person whose turn it is in the chain.
    (The HR & Admin department admin no longer decides in someone else's
    place — the chain is strictly in order, one named person per step.)"""
    return _can_act(db, user, app)

def _can_note(db, user, app):
    """Who can set the HR note: the person whose turn it is, and the HR
    & Admin department admin, while the application is undecided."""
    if app["status"] not in ("pending", "checked"):
        return False
    return _can_act(db, user, app) or _is_hr_dept_admin(db, user)

def _can_forward(db, user, app):
    """The old forward (checker forwards to HR & Admin) is kept only for
    a chain made the old way: a single step, still Pending, with the
    checker's signature on file. Picking the steps up front on the
    creation page replaces it everywhere else."""
    if not app["chain_legacy"]:
        return False
    if app["status"] != "pending":
        return False
    steps = _steps(db, app["id"])
    if len(steps) != 1:
        return False
    s = steps[0]
    return bool(s["signature_path"]) and s["user_id"] == user["id"] and s["status"] == "pending"

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

def _chain_people(db, dept_id):
    """Everyone a step in the approval chain can be sent to: active,
    approved users in the applicant's own department, HR & Admin and
    Management (when there is a department called Management).
    Department admins first in each department, then by name."""
    dept_ids = [dept_id]
    for _did in (hr_admin_dept_id(db), management_dept_id(db)):
        if _did and _did not in dept_ids:
            dept_ids.append(_did)
    rows = db.execute("SELECT id, full_name, designation, is_dept_admin, department_id FROM users "
                      "WHERE department_id IN (%s) AND is_active=1 AND is_deleted=0 AND approval_status='approved' "
                      "ORDER BY department_id, is_dept_admin DESC, full_name" % ",".join("?" * len(dept_ids)),
                      tuple(dept_ids)).fetchall()
    return rows

def _chain_depts(db, dept_id):
    """The departments _chain_people draws from, in the same order, for
    grouping the person dropdown."""
    dept_ids = [dept_id]
    for _did in (hr_admin_dept_id(db), management_dept_id(db)):
        if _did and _did not in dept_ids:
            dept_ids.append(_did)
    return db.execute("SELECT id, name FROM departments WHERE id IN (%s) ORDER BY id" % ",".join("?" * len(dept_ids)),
                      tuple(dept_ids)).fetchall()

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

def _signature_path(name):
    if not name:
        return None
    p = os.path.join(config.UPLOAD_DIR, "app_signatures", name)
    return p if os.path.exists(p) else None


def _use_my_signature():
    """Copy the logged-in user's saved signature (the PNG from My
    settings) into the application signatures folder, under a new random
    name, so the application keeps its own copy even if the user later
    changes their signature in My settings. Returns the new file name,
    or None when the user has no saved signature."""
    saved = g.user["signature_path"] if g.user is not None and "signature_path" in g.user.keys() else None
    if not saved:
        return None
    src = os.path.join(config.UPLOAD_DIR, "user_signatures", os.path.basename(saved))
    if not os.path.exists(src):
        return None
    folder = os.path.join(config.UPLOAD_DIR, "app_signatures")
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(10) + ".png"
    try:
        import shutil
        shutil.copyfile(src, os.path.join(folder, name))
    except Exception:
        return None
    return name

def _save_kind_logo(file_storage):
    """Save an uploaded kind logo (top left or top right corner of the
    letter). The file is stored as-is — a logo is branding, so it is not
    trimmed the way a signature is. Returns the stored file name, or None
    when nothing was uploaded or the file type is not allowed."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in SIG_EXTENSIONS:
        return None
    folder = os.path.join(config.UPLOAD_DIR, "app_kind_logos")
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(10) + "." + ext
    path = os.path.join(folder, name)
    file_storage.save(path)
    return name

def _kind_logo_path(name):
    if not name:
        return None
    p = os.path.join(config.UPLOAD_DIR, "app_kind_logos", name)
    return p if os.path.exists(p) else None

def _delete_kind_logo(name):
    if not name:
        return
    try:
        p = os.path.join(config.UPLOAD_DIR, "app_kind_logos", os.path.basename(name))
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass

def _notify_dept_admins(db, app, text, link):
    """The application's department admins are told, except the owner, the
    checker and the recipient — those three were already told directly in
    the same action (the owner gets "changed your application ...", the
    checker gets "... you checked ...", the recipient gets "... sent to
    you"). Without this, a department admin who is also the checker
    would get the same news twice, once as the checker and once as a
    department admin (2026-11-14)."""
    _admins = [r[0] for r in db.execute(
        "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1",
        (app["department_id"],))]
    _told = {app["owner_id"], app["checker_id"], app["recipient_id"]} | set(_step_user_ids(db, app["id"]))
    notify(db, [uid for uid in _admins if uid not in _told], text, link, skip=g.user["id"])

# ---------------------------------------------------------------- the page (inside More)
@bp.route("/applications")
@login_required
def list_applications():
    db = get_db()
    tab = (request.args.get("apptab") or "my").strip()
    if tab not in ("my", "all", "received"):
        tab = "my"
    is_hr = bool(hr_admin_dept_id(db)) and g.user["department_id"] == hr_admin_dept_id(db)
    # Who gets an All applications tab, and what it shows:
    # - the portal admin and the administrative permission users see
    #   every application from every department;
    # - a department admin sees his own department's applications,
    #   and the HR & Admin department admin also sees every
    #   application sent to one of his department's users;
    # - a regular user has no All tab at all: only his own
    #   applications (My) and the ones requested to him (Received).
    if is_portal_admin(g.user):
        all_scope = "everything"
    elif _is_dept_admin(g.user):
        all_scope = "dept"
    else:
        all_scope = "none"
    if tab == "all" and all_scope == "none":
        tab = "my"
    # The Received tab is for the person an application is currently
    # with: the person whose turn it is in the chain. HR users always
    # see it; anyone else sees it when something is currently with them.
    # Only applications still waiting for a decision count — once an
    # application is approved or rejected it goes nowhere, so it never
    # appears in anybody's Received tab.
    has_received = db.execute("SELECT 1 FROM applications WHERE recipient_id=? AND status IN ('pending','checked') AND deleted_at IS NULL LIMIT 1", (g.user["id"],)).fetchone() is not None
    show_received = bool(is_hr or has_received)
    if tab == "received" and not show_received:
        tab = "my"
    kinds = db.execute("SELECT * FROM application_kinds WHERE department_id=? AND status='active' ORDER BY id",
                       (g.user["department_id"],)).fetchall()
    # KPI counts for the current user (deleted applications are in the Recycle Bin, not here).
    counts = {"my": 0, "pending": 0, "checked": 0, "approved": 0, "rejected": 0}
    for r in db.execute("SELECT status, COUNT(*) c FROM applications WHERE owner_id=? AND deleted_at IS NULL GROUP BY status", (g.user["id"],)):
        counts["my"] += r["c"]
        counts[r["status"]] = counts.get(r["status"], 0) + r["c"]
    # The list. The department filter is only for the portal admin and
    # the administrative permission users, who see every department.
    can_all = all_scope == "everything"
    fdept = request.args.get("fdept", type=int)
    fstatus = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()
    where = ["a.deleted_at IS NULL"]
    params = []
    if tab == "my":
        where.append("a.owner_id=?"); params.append(g.user["id"])
    elif tab == "received":
        where.append("a.recipient_id=?"); params.append(g.user["id"])
        where.append("a.status IN ('pending','checked')")
    else:
        if all_scope == "dept":
            if _is_hr_dept_admin(db, g.user):
                hr = hr_admin_dept_id(db)
                where.append("(a.department_id=? OR EXISTS (SELECT 1 FROM application_steps s "
                             "JOIN users u ON u.id=s.user_id WHERE s.application_id=a.id AND u.department_id=?))")
                params += [g.user["department_id"], hr]
            else:
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
                           can_all=can_all, show_all=all_scope != "none", depts=depts, fdept=fdept, fstatus=fstatus, q=q,
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
        logo_left = _save_kind_logo(request.files.get("logo_left"))
        logo_right = _save_kind_logo(request.files.get("logo_right"))
        db.execute("INSERT INTO application_kinds(department_id,created_by,name,number_prefix,company_name,company_address,logo_left,logo_right,status) VALUES (?,?,?,?,?,?,?,?,?)",
                   (g.user["department_id"], g.user["id"], name, prefix, company_name, company_address, logo_left, logo_right, "active"))
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
        # Logos: uploading a new one replaces the old file; ticking Remove
        # clears that corner (it stays blank on the letter); uploading
        # nothing leaves the current logo in place.
        logo_left = kind["logo_left"]
        logo_right = kind["logo_right"]
        new_left = _save_kind_logo(request.files.get("logo_left"))
        if new_left:
            _delete_kind_logo(logo_left)
            logo_left = new_left
        elif request.form.get("remove_logo_left"):
            _delete_kind_logo(logo_left)
            logo_left = None
        new_right = _save_kind_logo(request.files.get("logo_right"))
        if new_right:
            _delete_kind_logo(logo_right)
            logo_right = new_right
        elif request.form.get("remove_logo_right"):
            _delete_kind_logo(logo_right)
            logo_right = None
        db.execute("UPDATE application_kinds SET name=?,number_prefix=?,company_name=?,company_address=?,logo_left=?,logo_right=?,status=?,updated_at=datetime('now','localtime') WHERE id=?",
                   (name, prefix, company_name, company_address, logo_left, logo_right, status, kid))
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
    chain_people = _chain_people(db, g.user["department_id"])
    chain_depts = _chain_depts(db, g.user["department_id"])
    if request.method == "POST" and kind is not None:
        # The approval chain: three steps, each with a role (None,
        # Checked By, Approved By or Authorised By) and a person from
        # the applicant's own department, HR & Admin or Management.
        # A step set to None is skipped — the steps are renumbered, so
        # two steps means two signature blocks, three means three.
        # The same person cannot be picked for two steps, and at least
        # one step must be chosen. The old single-recipient shape
        # (recipient_id, no step fields) still works: it makes a
        # one-step chain, Checked By that person, which the checker
        # may still forward to HR & Admin.
        chain = []
        legacy = 0
        error = None
        if any(request.form.get(f"step{i}_role") for i in (1, 2, 3)):
            seen = set()
            for i in (1, 2, 3):
                role = (request.form.get(f"step{i}_role") or "none").strip().lower()
                if role == "none":
                    continue
                if role not in STEP_ROLES:
                    error = "Choose a role for each step: None, Checked By, Approved By or Authorised By."
                    break
                try:
                    uid = int(request.form.get(f"step{i}_user") or 0)
                except ValueError:
                    uid = 0
                if uid not in [p["id"] for p in chain_people]:
                    error = "Choose a person from your department, HR & Admin or Management for each step."
                    break
                if uid in seen:
                    error = "Choose a different person for each step."
                    break
                seen.add(uid)
                chain.append((role, uid))
            else:
                if not chain:
                    error = "Choose at least one step — who approves this application?"
        else:
            try:
                recipient_id = int(request.form.get("recipient_id") or 0)
            except ValueError:
                recipient_id = 0
            if recipient_id not in [r["id"] for r in recipients]:
                error = "Choose a recipient from your own department."
            else:
                chain = [("checked", recipient_id)]
                legacy = 1
        from_date = (request.form.get("from_date") or "").strip()
        to_date = (request.form.get("to_date") or "").strip()
        reason = (request.form.get("reason") or "").strip()
        body = (request.form.get("letter_body") or "").strip()
        # The To box: the lines the user wrote for the letter's To section.
        # Nothing is filled in automatically — blank means nothing appears
        # under "To," (2026-11-14). Each row is one line; blank rows are
        # dropped when the letter is drawn.
        to_lines = "\n".join([l.strip() for l in (request.form.get("to_lines") or "").splitlines() if l.strip()])
        days = _days_between(from_date, to_date)
        if not error and (not from_date or not to_date or days < 1):
            error = "Choose a from date and a to date, with the to date on or after the from date."
        elif not error and not reason:
            error = "Write a reason for the leave."
        elif not error and not body:
            error = "Write the letter."
        if error:
            flash(error, "error")
        else:
            number = f"{kind['number_prefix']}-{kind['next_number']:04d}"
            db.execute("UPDATE application_kinds SET next_number=next_number+1 WHERE id=?", (kind["id"],))
            first_uid = chain[0][1]
            aid = db.execute("INSERT INTO applications(department_id,kind_id,owner_id,recipient_id,checker_id,number,status,from_date,to_date,days,reason,letter_body,to_lines,chain_legacy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (g.user["department_id"], kind["id"], g.user["id"], first_uid, first_uid, number, "pending",
                              from_date, to_date, days, reason, body, to_lines, legacy)).lastrowid
            for pos, (role, uid) in enumerate(chain, start=1):
                db.execute("INSERT INTO application_steps(application_id,position,role,user_id,status) VALUES (?,?,?,?,?)",
                           (aid, pos, role, uid, "pending"))
            _sync_app_from_steps(db, aid)
            _log_history(db, aid, g.user, "created", "", "", number)
            rec = db.execute("SELECT full_name, is_dept_admin FROM users WHERE id=?", (first_uid,)).fetchone()
            first_role = chain[0][0]
            log(db, "application_new", number)
            notify(db, [first_uid],
                   f"{g.user['full_name']} sent you a {kind['name']} {number} to {STEP_VERBS[first_role]}.",
                   url_for("applications.detail", aid=aid), skip=g.user["id"])
            _dept = db.execute("SELECT * FROM departments WHERE id=?", (g.user["department_id"],)).fetchone()
            # The watcher notification skips the first person: they were
            # just told directly above, and a first person who is also a
            # department admin would otherwise get the same news twice
            # (2026-11-14).
            notify_ddb_task(db, g.user, _dept,
                            f"{g.user['full_name']} sent a {kind['name']} {number} to {rec['full_name'] if rec else 'their department'} to {STEP_VERBS[first_role]}.",
                            url_for("applications.detail", aid=aid), skip=first_uid)
            # When a regular user sends an application to a department admin,
            # the portal admin and the administrative permission users are
            # told too (2026-11-14): they are told about every request a
            # department admin receives, not only about the tasks a
            # department admin sends. A department admin or permission user
            # sending it already told them through notify_ddb_task above,
            # so they are not told twice.
            if rec and rec["is_dept_admin"] and not _is_dept_admin(g.user) and not is_portal_admin(g.user):
                notify(db, true_admin_ids(db) + permission_user_ids(db),
                       f"{g.user['full_name']} sent a {kind['name']} {number} to {rec['full_name']} to {STEP_VERBS[first_role]}.",
                       url_for("applications.detail", aid=aid), skip=g.user["id"])
            db.commit()
            flash(f"Application {number} sent to {rec['full_name'] if rec else 'your department'} to {STEP_VERBS[first_role]}.", "ok")
            return redirect(url_for("applications.detail", aid=aid))
    return render_template("application_form.html", kind=kind, recipients=recipients,
                           chain_people=chain_people, chain_depts=chain_depts)

# ---------------------------------------------------------------- edit an application
@bp.route("/applications/<int:aid>/edit", methods=["GET", "POST"])
@login_required
def application_edit(aid):
    """Edit an application. The owner (only while Pending), the person
    whose turn it is in the chain and the HR & Admin dept admin can edit
    it. The number, the kind and the approval chain stay the same — only
    the from/to dates, the reason and the letter body can change. Saving
    writes one edit-log entry per changed field, logs the edit, and
    notifies the other party."""
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
        # The To box, same as on the create form (2026-11-14).
        to_lines = "\n".join([l.strip() for l in (request.form.get("to_lines") or "").splitlines() if l.strip()])
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
        if (app["to_lines"] or "") != to_lines:
            _log_history(db, aid, g.user, "edit", "To", app["to_lines"] or "", to_lines)
        db.execute("UPDATE applications SET from_date=?,to_date=?,days=?,reason=?,letter_body=?,to_lines=?,updated_at=datetime('now','localtime') WHERE id=?",
                   (from_date, to_date, days, reason, body, to_lines, aid))
        log(db, "application_edit", app["number"])
        if g.user["id"] == app["owner_id"]:
            notify(db, [app["recipient_id"]],
                   f"{g.user['full_name']} updated the {kind['name'] if kind else 'leave'} {app['number']} sent to you.",
                   url_for("applications.detail", aid=aid), skip=g.user["id"])
        else:
            notify(db, [app["owner_id"]],
                   f"{g.user['full_name']} updated your {kind['name'] if kind else 'leave'} {app['number']}.",
                   url_for("applications.detail", aid=aid), skip=g.user["id"])
        _notify_dept_admins(db, app, f"{g.user['full_name']} updated the application {app['number']}.",
                            url_for("applications.detail", aid=aid))
        # When a department admin edits an application, the portal admin
        # and the administrative permission users are told too (2026-11-14):
        # they are told about every task a department admin does. This
        # tells a different set from _notify_dept_admins above (which tells
        # the department admins), so nobody is told twice.
        if _is_dept_admin(g.user):
            notify_dept_task(db, g.user,
                             f"{g.user['full_name']} updated the application {app['number']}.",
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
    _adopt_mirrors(db, aid)
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
    _steps_list = _steps(db, aid)
    # Once the application is decided nobody is "currently with" it:
    # the request goes no further, so no step is waiting and nobody is
    # shown as the person holding it.
    _cur = _current_step(db, aid) if app["status"] in ("pending", "checked") else None
    _viewer = next((s for s in _steps_list if s["user_id"] == g.user["id"]), None)
    return render_template("application_detail.html", app=app, kind=kind,
                           owner=owner, recipient=recipient, checker=checker, approver=approver,
                           dept=dept, signer=signer,
                           qr_svg=qr_svg, qr_url=qr_url,
                           my_signature=g.user["signature_path"] if g.user is not None and "signature_path" in g.user.keys() else None,
                           steps=_steps_list, current_step=_cur, viewer_step=_viewer,
                           step_roles=STEP_ROLES,
                           can_act=_can_act(db, g.user, app),
                           can_forward=_can_forward(db, g.user, app),
                           can_note=_can_note(db, g.user, app),
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
    # Tell the other party, and only them (2026-11-14): when the portal
    # admin or an administrative permission user deletes it, only the owner
    # is told; when the owner deletes it, the checker / approver is told.
    # Nobody else — not the department admins, not HR — is told about a delete.
    other = app["recipient_id"] if g.user["id"] == app["owner_id"] else app["owner_id"]
    if other and other != g.user["id"]:
        notify(db, [other],
               f"{g.user['full_name']} deleted the application {app['number']}. It is in the Recycle Bin for 30 days.",
               url_for("applications.list_applications"), skip=g.user["id"])
    db.commit()
    flash(f"Application {app['number']} deleted. It is in the Recycle bin for {config.BIN_DAYS} days — it can be restored from there.", "ok")
    return redirect(url_for("applications.list_applications"))

# ---------------------------------------------------------------- sign and decide (the chain)
def _sign_current_step(aid, route_name):
    """The person whose turn it is ticks "Use my signature": their saved
    signature (the PNG from My settings) is copied onto the application
    under their step's role, so it stays as it was even if they later
    change their signature in My settings. They must have used their
    signature before they can approve or reject. The same handler serves
    the old /check-signature and /signature routes and the new
    /step-signature route, so applications made the old way keep working."""
    db = get_db(); app = _app(db, aid)
    if not _can_act(db, g.user, app):
        abort(403)
    _adopt_mirrors(db, aid)
    step = _current_step(db, aid)
    label = STEP_ROLES.get(step["role"], step["role"]) if step else ""
    if not request.form.get("use_my_signature"):
        flash("Tick 'Use my signature' to use the signature you saved in My settings.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    name = _use_my_signature()
    if not name:
        flash("You haven't uploaded a signature yet — upload one in My settings first.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    if step["signature_path"]:
        try:
            old = os.path.join(config.UPLOAD_DIR, "app_signatures", os.path.basename(step["signature_path"]))
            if os.path.exists(old):
                os.remove(old)
        except Exception:
            pass
    db.execute("UPDATE application_steps SET signature_path=?,signature_at=datetime('now','localtime') WHERE id=?",
               (name, step["id"]))
    _sync_app_from_steps(db, aid)
    _log_history(db, aid, g.user, "edit", f"{label} signature", "", g.user["full_name"])
    log(db, "application_step_signature", f"{app['number']} step {step['position']} {step['role']}")
    db.commit()
    steps = _steps(db, aid)
    if app["chain_legacy"] and step["position"] == 1 and len(steps) == 1:
        extra = " You can now forward the application to HR & Admin."
    elif step["position"] == len(steps):
        extra = ""
    else:
        extra = " You can now approve or reject the application."
    flash(f"Your signature has been added under {label}.{extra}", "ok")
    return redirect(url_for("applications.detail", aid=aid))

@bp.route("/applications/<int:aid>/check-signature", methods=["POST"])
@login_required
def check_signature(aid):
    return _sign_current_step(aid, "check_signature")

@bp.route("/applications/<int:aid>/signature", methods=["POST"])
@login_required
def upload_signature(aid):
    return _sign_current_step(aid, "upload_signature")

@bp.route("/applications/<int:aid>/step-signature", methods=["POST"])
@login_required
def step_signature(aid):
    return _sign_current_step(aid, "step_signature")

@bp.route("/applications/<int:aid>/forward", methods=["POST"])
@login_required
def forward_to_hr(aid):
    """The old forward, kept only for a chain made the old way: a single
    step, still Pending, with the checker's signature on file. The
    checker forwards the application to ONE specific HR & Admin user,
    which adds the second step (Approved By) and approves the first.
    Forwarding sets the status to Checked, makes the HR user the person
    it is currently with, and notifies the HR user and the owner."""
    db = get_db(); app = _app(db, aid)
    _adopt_mirrors(db, aid)
    _steps0 = _steps(db, aid)
    if (app["chain_legacy"] and app["status"] == "pending" and len(_steps0) == 1
            and _steps0[0]["user_id"] == g.user["id"] and _steps0[0]["status"] == "pending"
            and not _steps0[0]["signature_path"]):
        flash("Use your signature first — you can only forward the application once your signature is under Checked By.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    if not _can_forward(db, g.user, app):
        abort(403)
    try:
        hr_id = int(request.form.get("hr_user_id") or 0)
    except ValueError:
        hr_id = 0
    hr_users = hr_admin_users(db)
    if hr_id not in [r["id"] for r in hr_users]:
        flash("Choose an HR & Admin user to forward it to.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    steps = _steps(db, aid)
    db.execute("UPDATE application_steps SET status='approved' WHERE id=?", (steps[0]["id"],))
    db.execute("INSERT INTO application_steps(application_id,position,role,user_id,status) VALUES (?,?,?,?,?)",
               (aid, 2, "approved", hr_id, "pending"))
    db.execute("UPDATE applications SET status='checked',updated_at=datetime('now','localtime') WHERE id=?", (aid,))
    _sync_app_from_steps(db, aid)
    _log_history(db, aid, g.user, "status", "Status", STATUS_LABELS["pending"], STATUS_LABELS["checked"])
    log(db, "application_forwarded", f"{app['number']} -> HR user {hr_id}")
    hr = db.execute("SELECT full_name FROM users WHERE id=?", (hr_id,)).fetchone()
    notify(db, [hr_id],
           f"{g.user['full_name']} checked the application {app['number']} and forwarded it to you for approval.",
           url_for("applications.detail", aid=aid), skip=g.user["id"])
    notify(db, [app["owner_id"]],
           f"{g.user['full_name']} checked your application {app['number']} and forwarded it to {hr['full_name'] if hr else 'HR & Admin'}.",
           url_for("applications.detail", aid=aid), skip=g.user["id"])
    # The watchers are told too (2026-11-14): when a department admin
    # checks and forwards an application, the portal admin and the
    # administrative permission users are told; when a regular user does
    # it, that department's department admins are told. The router sends
    # it to the right watchers for whoever the checker is. The owner is
    # skipped here — they were just told directly above, and would
    # otherwise get the same news twice if they are also a department
    # admin (2026-11-14).
    _dept = db.execute("SELECT * FROM departments WHERE id=?", (app["department_id"],)).fetchone()
    notify_ddb_task(db, g.user, _dept,
                    f"{g.user['full_name']} checked the application {app['number']} and forwarded it to {hr['full_name'] if hr else 'HR & Admin'}.",
                    url_for("applications.detail", aid=aid), skip=app["owner_id"])
    db.commit()
    flash(f"Application {app['number']} forwarded to {hr['full_name'] if hr else 'HR & Admin'}. It is now Checked.", "ok")
    return redirect(url_for("applications.detail", aid=aid))

def _decide(aid):
    """The person whose turn it is approves or rejects the application.
    They must have ticked "Use my signature" first — their signature has
    to be on file for their step. Approving moves the application to the
    next step (status Checked) until the last step approves it (status
    Approved). Rejecting ends the application at once (status Rejected).
    The last step's decision is the only one that shows the watermark:
    the grey APPROVED seal when the last step approves, the grey
    REJECTED stamp when the last step rejects. The same handler serves
    the old /status route and the new /decide route."""
    db = get_db(); app = _app(db, aid)
    if not _can_act(db, g.user, app):
        abort(403)
    _adopt_mirrors(db, aid)
    step = _current_step(db, aid)
    steps = _steps(db, aid)
    label = STEP_ROLES.get(step["role"], step["role"]) if step else ""
    is_last = bool(step) and step["position"] == len(steps)
    new_status = (request.form.get("status") or "").strip()
    if new_status not in ("approved", "rejected"):
        flash("Choose a status: Approved or Rejected.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    if new_status == app["status"]:
        flash("Status is already " + STATUS_LABELS[new_status] + ".", "ok")
        return redirect(url_for("applications.detail", aid=aid))
    if not step or not step["signature_path"]:
        flash(f"Use your signature first — you can only save the status once your signature is under {label}.", "error")
        return redirect(url_for("applications.detail", aid=aid))
    db.execute("UPDATE application_steps SET status=? WHERE id=?", (new_status, step["id"]))
    if new_status == "approved" and not is_last:
        new_app_status = "checked"
    else:
        new_app_status = new_status
    db.execute("UPDATE applications SET status=?,updated_at=datetime('now','localtime') WHERE id=?", (new_app_status, aid))
    _sync_app_from_steps(db, aid)
    if new_status == "approved" and not is_last:
        # The application stays "Checked" — log the step's own decision
        # as an edit ("Step 2 (Approved By): Pending → Approved"),
        # because the status line would read "from Checked to Checked",
        # which says nothing happened.
        _log_history(db, aid, g.user, "edit", f"Step {step['position']} ({label})",
                     "Pending", "Approved")
    else:
        _log_history(db, aid, g.user, "status", "Status", STATUS_LABELS.get(app["status"], app["status"]), STATUS_LABELS[new_app_status])
    log(db, "application_status", f"{app['number']} -> {new_app_status}")
    nxt = _current_step(db, aid)
    nxt_name = nxt["full_name"] if nxt else ""
    # Who is told: the owner and the people who already decided are
    # told directly; the next person is told when it becomes their turn;
    # the department admins and the watchers above them are told the
    # same way as before. The wording for the LAST step's decision is
    # unchanged from before ("changed your application ... to
    # Approved."), so nobody's notification history changes meaning.
    if new_status == "approved" and not is_last:
        notify(db, [nxt["user_id"]] if nxt else [],
               f"{g.user['full_name']} approved the application {app['number']} and sent it to you to {STEP_VERBS[nxt['role']]}.",
               url_for("applications.detail", aid=aid), skip=g.user["id"])
        notify(db, [app["owner_id"]],
               f"{g.user['full_name']} approved your application {app['number']} — it is now with {nxt_name}.",
               url_for("applications.detail", aid=aid), skip=g.user["id"])
        for _s in steps:
            if _s["position"] < step["position"] and _s["user_id"] and _s["user_id"] != app["owner_id"]:
                notify(db, [_s["user_id"]],
                       f"{g.user['full_name']} approved the application {app['number']} — it is now with {nxt_name}.",
                       url_for("applications.detail", aid=aid), skip=g.user["id"])
        _notify_dept_admins(db, app, f"{g.user['full_name']} approved the application {app['number']} — it is now with {nxt_name}.",
                            url_for("applications.detail", aid=aid))
        if _is_dept_admin(g.user):
            notify_dept_task(db, g.user,
                             f"{g.user['full_name']} approved the application {app['number']} — it is now with {nxt_name}.",
                             url_for("applications.detail", aid=aid))
        elif is_portal_admin(g.user):
            notify_admin_task(db, g.user,
                              f"{g.user['full_name']} approved the application {app['number']} — it is now with {nxt_name}.",
                              url_for("applications.detail", aid=aid))
    else:
        notify(db, [app["owner_id"]],
               f"{g.user['full_name']} changed your application {app['number']} to {STATUS_LABELS[new_status]}.",
               url_for("applications.detail", aid=aid), skip=g.user["id"])
        for _s in steps:
            if _s["position"] < step["position"] and _s["user_id"] and _s["user_id"] != app["owner_id"]:
                notify(db, [_s["user_id"]],
                       f"{g.user['full_name']} changed the application {app['number']} you {STEP_PAST[_s['role']]} to {STATUS_LABELS[new_status]}.",
                       url_for("applications.detail", aid=aid), skip=g.user["id"])
        _notify_dept_admins(db, app, f"{g.user['full_name']} changed the application {app['number']} to {STATUS_LABELS[new_status]}.",
                            url_for("applications.detail", aid=aid))
        # The watchers above the department are told too (2026-11-14):
        # when a department admin approves or rejects, the portal admin
        # and the administrative permission users are told; when a
        # permission user does it, the true portal admins are told. A
        # regular user deciding tells the department admins, which
        # _notify_dept_admins above already does, so they are not told
        # twice. (notify_ddb_task is NOT used here: it routes by
        # whether the actor is a department admin of the application's
        # department, and an HR or Management department admin is a
        # department admin of a different department, so it would
        # wrongly treat them as a regular user.)
        if _is_dept_admin(g.user):
            notify_dept_task(db, g.user,
                             f"{g.user['full_name']} changed the application {app['number']} to {STATUS_LABELS[new_status]}.",
                             url_for("applications.detail", aid=aid))
        elif is_portal_admin(g.user):
            notify_admin_task(db, g.user,
                              f"{g.user['full_name']} changed the application {app['number']} to {STATUS_LABELS[new_status]}.",
                              url_for("applications.detail", aid=aid))
    db.commit()
    if new_status == "approved" and not is_last:
        flash(f"Status changed to {STATUS_LABELS[new_app_status]}. The application is now with {nxt_name}.", "ok")
    else:
        flash(f"Status changed to {STATUS_LABELS[new_status]}. The applicant and the earlier approvers have been notified.", "ok")
    return redirect(url_for("applications.detail", aid=aid))

@bp.route("/applications/<int:aid>/status", methods=["POST"])
@login_required
def change_status(aid):
    return _decide(aid)

@bp.route("/applications/<int:aid>/decide", methods=["POST"])
@login_required
def decide(aid):
    return _decide(aid)

@bp.route("/applications/<int:aid>/note", methods=["POST"])
@login_required
def set_note(aid):
    db = get_db(); app = _app(db, aid)
    if not _can_note(db, g.user, app):
        abort(403)
    note = (request.form.get("hr_note") or "").strip()
    db.execute("UPDATE applications SET hr_note=?,updated_at=datetime('now','localtime') WHERE id=?", (note, aid))
    if (app["hr_note"] or "") != note:
        _log_history(db, aid, g.user, "edit", "HR note", app["hr_note"] or "", note)
    log(db, "application_note", app["number"])
    db.commit()
    flash("HR note saved.", "ok")
    return redirect(url_for("applications.detail", aid=aid))

def _step_signature_name(db, app, kind):
    """The signature file for a signature-image route: 'checker' is the
    Checked By step (or the first step), 'approver' is the last step,
    'step-1'/'step-2'/'step-3' is that step. None when there is none."""
    steps = _steps(db, app["id"])
    if not steps:
        return None
    if kind == "checker":
        s = next((x for x in steps if x["role"] == "checked"), steps[0])
        return s["signature_path"]
    if kind == "approver":
        return steps[-1]["signature_path"]
    if kind.startswith("step-"):
        try:
            pos = int(kind[5:])
        except ValueError:
            return None
        s = next((x for x in steps if x["position"] == pos), None)
        return s["signature_path"] if s else None
    return None

@bp.route("/applications/<int:aid>/signature/<kind>")
@login_required
def signature_image(aid, kind):
    """Serve a signature image inline for the detail page letter preview.
    kind is 'checker', 'approver' or 'step-1'/'step-2'/'step-3'. Only users
    who can view the application can see it."""
    from flask import send_file
    db = get_db(); app = _app(db, aid)
    if not _can_view(db, g.user, app):
        abort(403)
    path = _signature_path(_step_signature_name(db, app, kind))
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
    path = _signature_path(_step_signature_name(db, app, kind))
    if not path:
        abort(404)
    return send_file(path)

@bp.route("/applications/kinds/<int:kid>/logo/<side>")
@login_required
def kind_logo(kid, side):
    """Serve a kind logo image inline for the kind form preview. side is
    'left' or 'right'. Only a department admin of the kind's department
    can see it."""
    from flask import send_file
    db = get_db(); kind = _kind(db, kid)
    if not _is_dept_admin(g.user) or kind["department_id"] != g.user["department_id"]:
        abort(403)
    if side not in ("left", "right"):
        abort(404)
    path = _kind_logo_path(kind["logo_left"] if side == "left" else kind["logo_right"])
    if not path:
        abort(404)
    return send_file(path)

@bp.route("/applications/<int:aid>/logo/<side>")
@login_required
def kind_logo_image(aid, side):
    """Serve a kind logo image inline for the detail page letter preview.
    side is 'left' or 'right'. Only users who can view the application
    can see its kind's logos."""
    from flask import send_file
    db = get_db(); app = _app(db, aid)
    if not _can_view(db, g.user, app):
        abort(403)
    kind = _kind(db, app["kind_id"]) if app["kind_id"] else None
    if kind is None or side not in ("left", "right"):
        abort(404)
    path = _kind_logo_path(kind["logo_left"] if side == "left" else kind["logo_right"])
    if not path:
        abort(404)
    return send_file(path)

@bp.route("/applications/code/<code>/logo/<side>")
def code_kind_logo_image(code, side):
    """Serve a kind logo image inline for the public code page letter
    preview. Public, like the code PDF — only when the application's
    public QR is on and it is not deleted."""
    from flask import send_file
    db = get_db()
    app = db.execute("SELECT * FROM applications WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if app is None or app["deleted_at"] or not _public_check(db, app):
        abort(404)
    kind = _kind(db, app["kind_id"]) if app["kind_id"] else None
    if kind is None or side not in ("left", "right"):
        abort(404)
    path = _kind_logo_path(kind["logo_left"] if side == "left" else kind["logo_right"])
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
                           steps=_steps(db, app["id"]), step_roles=STEP_ROLES,
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
    # One signature block per step in the chain, in order — a step set
    # to None at creation has no block at all. A step that rejected
    # shows "Rejected By" above their name instead of their role. The
    # watermark: the REJECTED stamp appears as soon as ANY step
    # rejects, and the request goes no further; the APPROVED seal
    # appears only when the LAST step approves. An approval by an
    # earlier step shows no watermark at all.
    steps = _steps(db, app["id"])
    sig_blocks = [(_signature_path(s["signature_path"]),
                   "Rejected By" if s["status"] == "rejected" else STEP_ROLES.get(s["role"], s["role"]),
                   s["full_name"] or "", s["designation"] or "", s["dept_name"] or "") for s in steps]
    last = steps[-1] if steps else None
    if any(s["status"] == "rejected" for s in steps):
        wm_status = "rejected"
    elif last and last["status"] == "approved":
        wm_status = "approved"
    else:
        wm_status = "pending"
    return exports.application_pdf(
        number=app["number"] or "", app_date=app["created_at"][:10] if app["created_at"] else "",
        kind_name=kind["name"] if kind else "", status=wm_status,
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
        company=company, company_address=address, qr_url=qr_url,
        sig_blocks=sig_blocks,
        to_lines=app["to_lines"] or "",
        logo_left=_kind_logo_path(kind["logo_left"]) if kind else None,
        logo_right=_kind_logo_path(kind["logo_right"]) if kind else None)
