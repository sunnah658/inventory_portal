"""
routes_requests.py - Item Requests (NEW in this version, section 49 in README).

A default "Request items" tab inside Department Database (like Invoices).
A dept admin makes an Item Request kind for their OWN department (like an
invoice template). A user picks a kind in the Request items tab, fills in
the items, and picks up to 3 approval steps — one step and only one step
being "Send/Request To", the person who receives the request — from their
own department, HR & Admin or Management. The steps run in order, each
person must tick "Use my signature" before approving or rejecting, and
the request's status follows the chain: Pending while it forwards,
Approved when the last person approves (the APPROVED seal appears on the
PDF), Rejected as soon as anyone rejects (the REJECTED stamp appears).
Once approved, the Send/Request To user changes the status: Pending ->
Issued -> Paid -> Handovered. The recipient sees the request in their
"Other's request" sub-tab, and can print it and download its PDF. A new
request starts as Pending. When the Send/Request To user changes the
status, the creator is notified and can see the new status in
"My request".

Sub-tabs: My request (only the current user's requests), All request,
Other's request (only requests sent TO the current user). In All request,
the portal admin, administrative permission users and HR & Admin users
see ALL departments' requests; users of other departments see only their
own department's requests. The All request filter is BOTH department and
status, with a search bar (search by name or Department).

Public QR for requests: HRC- + random 5-digit code, e.g. HRC-48392 — the
same random-code system as invoices and records. Searching a code,
viewing it and downloading its PDF all need a login. A new scan link
kills the old code. Currency sits beside every amount; one request has
one currency, no auto-conversion. Two logos (left + right top corner) and
the "Item Request" title centred at the top, as approved in the JPG.

Used by: app.py (registers it). Uses: core.py, auth.py, models.py, exports.py, config.py
Templates: request_*.html, deptdb_requests.html
"""
import json
import os
import secrets
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import segno
from flask import (Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for)

import config
import exports
from auth import login_required
from utils import is_portal_admin
from core import external_url, notify, notify_admin_task, notify_ddb_row_task, notify_ddb_task, notify_dept_task
from models import get_db, log, setting_get

bp = Blueprint("requests", __name__)
CURRENCIES = ["BDT", "USD", "EUR", "GBP", "INR"]
STATUSES = ["pending", "issued", "paid", "handovered"]
ALL_STATUSES = ["pending", "issued", "paid", "handovered", "approved", "rejected"]
STATUS_LABELS = {"pending": "Pending", "issued": "Issued", "paid": "Paid", "handovered": "Handovered", "approved": "Approved", "rejected": "Rejected"}

# ---------------------------------------------------------------- helpers
def _money(v):
    try:
        return Decimal(str(v).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, AttributeError):
        return Decimal("0.00")

def _fmt(v, cur="BDT"):
    return f"{_money(v):,.2f} {cur}"

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
def _words(n):
    if n == 0:
        return "Zero"
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " Hundred" + (" " + _words(n % 100) if n % 100 else "")
    if n < 1000000:
        return _words(n // 1000) + " Thousand" + (" " + _words(n % 1000) if n % 1000 else "")
    return _words(n // 1000000) + " Million" + (" " + _words(n % 1000000) if n % 1000000 else "")

def amount_in_words(total, cur):
    word = {"BDT": "Taka", "USD": "Dollars", "EUR": "Euros", "GBP": "Pounds", "INR": "Rupees"}.get(cur, cur)
    whole = int(_money(total))
    return f"{_words(whole)} {word} Only"

def _is_dept_admin(user):
    return bool(user and user["is_dept_admin"])

def _dept_admin_required():
    if not _is_dept_admin(g.user):
        abort(403)

def _kind(db, kid):
    row = db.execute("SELECT * FROM item_request_kinds WHERE id=?", (kid,)).fetchone()
    if row is None:
        abort(404)
    return row

def _request(db, rid):
    row = db.execute("SELECT * FROM item_requests WHERE id=?", (rid,)).fetchone()
    if row is None:
        abort(404)
    return row

def hr_admin_dept_id(db):
    """The HR & Admin department id, by name (the department requests are sent to)."""
    row = db.execute("SELECT id FROM departments WHERE LOWER(name)='hr & admin'").fetchone()
    if row:
        return row["id"]
    row = db.execute("SELECT id FROM departments WHERE LOWER(name) LIKE '%hr%' AND LOWER(name) LIKE '%admin%' ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None

def management_dept_id(db):
    """The Management department id, by name — the third department an
    application step can be sent to (2026-11-14). None when there is no
    department called Management yet; then no Management users appear in
    the person list."""
    row = db.execute("SELECT id FROM departments WHERE LOWER(name)='management'").fetchone()
    return row["id"] if row else None

def hr_admin_users(db):
    """Active, approved users in the HR & Admin department — the only people a request can be sent to."""
    did = hr_admin_dept_id(db)
    if not did:
        return []
    return db.execute("SELECT id, full_name, username FROM users WHERE department_id=? AND is_active=1 AND is_deleted=0 AND approval_status='approved' ORDER BY full_name",
                      (did,)).fetchall()

def can_see_all_departments(db, user):
    """Portal admin, administrative permission user, or an HR & Admin department user: sees all departments' requests in All request."""
    if is_portal_admin(user):
        return True
    did = hr_admin_dept_id(db)
    return bool(did) and user["department_id"] == did

def _can_view(db, user, req):
    if is_portal_admin(user):
        return True
    if req["owner_id"] == user["id"]:
        return True
    if req["recipient_id"] == user["id"]:
        return True
    # Every user in the same department can see that department's requests
    # (they appear in that department's All request sub-tab).
    if user["department_id"] == req["department_id"]:
        return True
    # Any HR & Admin user can open and see every request (they all appear
    # in the All request section), whatever department it came from.
    # Only the recipient can edit it — _can_edit is unchanged.
    if user["department_id"] == hr_admin_dept_id(db):
        return True
    # Anyone picked as a step on this request can open it and its PDF —
    # whatever department they are in — so an approver from another
    # department is never met with a 403. They can only approve or
    # reject when their turn comes; _can_act_request is unchanged.
    if db.execute("SELECT 1 FROM item_request_steps WHERE request_id=? AND user_id=?",
                  (req["id"], user["id"])).fetchone():
        return True
    return False

def _can_change_status(db, user, req):
    """Only the Send/Request To user changes the status — and only once the approval chain has finished (every step decided). While the chain is still running, the chain decides the status."""
    if req["recipient_id"] != user["id"]:
        return False
    return all(s["status"] != "pending" for s in _request_steps(db, req["id"]))

def _can_manage_public(db, user, req):
    return (is_portal_admin(user) or req["owner_id"] == user["id"] or req["recipient_id"] == user["id"]
            or (_is_dept_admin(user) and req["department_id"] == user["department_id"]))

def _lines(db, rid):
    return db.execute("SELECT * FROM item_request_lines WHERE request_id=? ORDER BY position, id", (rid,)).fetchall()

def _can_edit(db, user, req):
    """Both the owner (the user who made the request) and the recipient (the
    Send/Request To user it was sent to) can edit the request record. Nobody else
    — not the portal admin, not other users in the department — can edit it."""
    return req["owner_id"] == user["id"] or req["recipient_id"] == user["id"]

# ---------------------------------------------------------------- approval chain
# A request is approved the same way as an application letter: the owner
# picks up to 3 steps when the request is sent (role + a person from their
# own department, HR & Admin or Management), one step and only one step
# being "Send/Request To" — the person who receives the request. The steps
# run in order, each person must tick "Use my signature" before approving
# or rejecting, and the request's status follows the chain — Pending while
# it forwards, Approved when the last person approves (the APPROVED seal
# appears on the PDF), Rejected as soon as anyone rejects (the REJECTED
# stamp appears). Once approved, the Send/Request To user changes the
# status to Pending, Issued, Paid or Handovered.
REQUEST_STEP_ROLES = {"checked": "Checked By", "send_to": "Send/Request To", "approved": "Approved By", "authorised": "Authorised By"}
REQUEST_STEP_VERBS = {"checked": "check", "send_to": "receive", "approved": "approve", "authorised": "authorise"}

def _request_steps(db, rid):
    """The approval chain for a request, in order, with each step's user's name, designation and department. A step whose user was purged has user_id None and no name — it still shows, with a blank name."""
    return db.execute("SELECT s.*, u.full_name, u.designation, d.name AS dept_name FROM item_request_steps s "
                      "LEFT JOIN users u ON u.id=s.user_id LEFT JOIN departments d ON d.id=u.department_id "
                      "WHERE s.request_id=? ORDER BY s.position", (rid,)).fetchall()

def _current_request_step(db, rid):
    """The first step that has not decided yet — the person it is currently with. None once every step has decided."""
    for s in _request_steps(db, rid):
        if s["status"] == "pending":
            return s
    return None

def _request_step_user_ids(db, rid):
    return [s["user_id"] for s in _request_steps(db, rid) if s["user_id"]]

def _sync_request_from_steps(db, rid):
    """Keep the request's status in step with its chain, and keep the
    recipient the Send/Request To user: Rejected as soon as any step
    rejects, Approved once every step has approved, Pending while any
    step is still waiting."""
    steps = _request_steps(db, rid)
    if not steps:
        return
    if any(s["status"] == "rejected" for s in steps):
        new_status = "rejected"
    elif all(s["status"] == "approved" for s in steps):
        new_status = "approved"
    else:
        new_status = "pending"
    send_to = next((s for s in steps if s["role"] == "send_to"), None)
    db.execute("UPDATE item_requests SET status=?,recipient_id=?,updated_at=datetime('now','localtime') WHERE id=?",
               (new_status, send_to["user_id"] if send_to else None, rid))

def _request_chain_people(db, dept_id):
    """Everyone a step in a request chain can be sent to: active, approved
    users in the owner's own department, HR & Admin and Management (when
    there is a department called Management). Department admins first in
    each department, then by name."""
    dept_ids = [dept_id]
    for _did in (hr_admin_dept_id(db), management_dept_id(db)):
        if _did and _did not in dept_ids:
            dept_ids.append(_did)
    rows = db.execute("SELECT id, full_name, designation, is_dept_admin, department_id FROM users "
                      "WHERE department_id IN (%s) AND is_active=1 AND is_deleted=0 AND approval_status='approved' "
                      "ORDER BY department_id, is_dept_admin DESC, full_name" % ",".join("?" * len(dept_ids)),
                      tuple(dept_ids)).fetchall()
    return rows

def _request_chain_depts(db, dept_id):
    """The departments _request_chain_people draws from, in the same order, for grouping the person dropdown."""
    dept_ids = [dept_id]
    for _did in (hr_admin_dept_id(db), management_dept_id(db)):
        if _did and _did not in dept_ids:
            dept_ids.append(_did)
    return db.execute("SELECT id, name FROM departments WHERE id IN (%s) ORDER BY id" % ",".join("?" * len(dept_ids)),
                      tuple(dept_ids)).fetchall()

def _parse_request_chain(form, people):
    """Read the three step rows (stepN_role / stepN_user) from the form. Returns (chain, error): chain is a list of (role, user_id) in order. At least one step must be chosen, no person twice, every person must be one of the chain people, and exactly one step must be Send/Request To — the person who receives the request."""
    chain = []
    seen = set()
    ids = {p["id"] for p in people}
    for i in (1, 2, 3):
        role = (form.get(f"step{i}_role") or "none").strip().lower()
        if role == "none":
            continue
        if role not in REQUEST_STEP_ROLES:
            return None, "Choose a role for each step: None, Checked By, Send/Request To, Approved By or Authorised By."
        try:
            uid = int(form.get(f"step{i}_user") or 0)
        except ValueError:
            uid = 0
        if uid not in ids:
            return None, "Choose a person from your department, HR & Admin or Management for each step."
        if uid in seen:
            return None, "Choose a different person for each step."
        seen.add(uid)
        chain.append((role, uid))
    if not chain:
        return None, "Choose at least one step — who approves this request?"
    if sum(1 for role, _uid in chain if role == "send_to") != 1:
        return None, "Choose exactly one step as Send/Request To — the person who receives the request."
    return chain, None

def _chain_from_form(form):
    """The step rows as the form sent them, for re-showing the form after an error: a list of {"role": ..., "user_id": ...} dicts, one per used step."""
    out = []
    for i in (1, 2, 3):
        role = (form.get(f"step{i}_role") or "none").strip().lower()
        if role == "none":
            continue
        try:
            uid = int(form.get(f"step{i}_user") or 0)
        except ValueError:
            uid = 0
        out.append({"role": role, "user_id": uid})
    return out

def _save_request_chain(db, rid, chain):
    db.execute("DELETE FROM item_request_steps WHERE request_id=?", (rid,))
    for pos, (role, uid) in enumerate(chain, start=1):
        db.execute("INSERT INTO item_request_steps(request_id,position,role,user_id) VALUES (?,?,?,?)", (rid, pos, role, uid))

def _use_my_signature_for(folder):
    """Copy the logged-in user's saved signature (the PNG from My settings) into the given signatures folder, under a new random name, so the document keeps its own copy even if the user later changes their signature in My settings. Returns the new file name, or None when the user has no saved signature."""
    saved = g.user["signature_path"] if g.user is not None and "signature_path" in g.user.keys() else None
    if not saved:
        return None
    src = os.path.join(config.UPLOAD_DIR, "user_signatures", os.path.basename(saved))
    if not os.path.exists(src):
        return None
    dest = os.path.join(config.UPLOAD_DIR, folder)
    os.makedirs(dest, exist_ok=True)
    name = secrets.token_hex(10) + ".png"
    try:
        import shutil
        shutil.copyfile(src, os.path.join(dest, name))
    except Exception:
        return None
    return name

def _can_act_request(db, user, req):
    """Only the person whose turn it is in the chain can approve or reject, and only while the request is Pending (the chain is still running)."""
    if req["status"] != "pending":
        return False
    step = _current_request_step(db, req["id"])
    return bool(step and step["user_id"] == user["id"])

def _notify_request_watchers(db, req, rid, text, link):
    """The request's department admins are told, except the owner and the chain people — those were already told directly in the same action. A dept-admin actor is also told to the portal admin and permission users above them, a permission-user actor to the portal admin."""
    _admins = [r[0] for r in db.execute(
        "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1",
        (req["department_id"],))]
    _told = {req["owner_id"]} | set(_request_step_user_ids(db, rid))
    notify(db, [uid for uid in _admins if uid not in _told], text, link, skip=g.user["id"])
    if _is_dept_admin(g.user):
        notify_dept_task(db, g.user, text, link)
    elif is_portal_admin(g.user):
        notify_admin_task(db, g.user, text, link)

def _sign_request_step(rid):
    """The person whose turn it is ticks "Use my signature": their saved signature is copied onto the request under their step's role. They must have used their signature before they can approve or reject."""
    db = get_db(); req = _request(db, rid)
    if not _can_act_request(db, g.user, req):
        abort(403)
    step = _current_request_step(db, rid)
    label = REQUEST_STEP_ROLES.get(step["role"], step["role"]) if step else ""
    if not request.form.get("use_my_signature"):
        flash("Tick 'Use my signature' to use the signature you saved in My settings.", "error")
        return redirect(url_for("requests.detail", rid=rid))
    name = _use_my_signature_for("req_signatures")
    if not name:
        flash("You haven't uploaded a signature yet — upload one in My settings first.", "error")
        return redirect(url_for("requests.detail", rid=rid))
    if step["signature_path"]:
        try:
            old = os.path.join(config.UPLOAD_DIR, "req_signatures", os.path.basename(step["signature_path"]))
            if os.path.exists(old):
                os.remove(old)
        except Exception:
            pass
    db.execute("UPDATE item_request_steps SET signature_path=?,signature_at=datetime('now','localtime') WHERE id=?", (name, step["id"]))
    _log_history(db, rid, g.user, "edit", f"{label} signature", "", g.user["full_name"])
    log(db, "request_step_signature", f"{req['number']} step {step['position']} {step['role']}")
    db.commit()
    flash(f"Your signature has been added under {label}. You can now approve or reject the request.", "ok")
    return redirect(url_for("requests.detail", rid=rid))

def _decide_request(rid):
    """The person whose turn it is approves or rejects the request. They must have ticked "Use my signature" first. Approving moves it to the next step until the last step approves (status Approved, and the APPROVED seal appears on the PDF). Rejecting ends it at once (status Rejected, and the REJECTED stamp appears on the PDF)."""
    db = get_db(); req = _request(db, rid)
    if not _can_act_request(db, g.user, req):
        abort(403)
    step = _current_request_step(db, rid)
    steps = _request_steps(db, rid)
    label = REQUEST_STEP_ROLES.get(step["role"], step["role"]) if step else ""
    is_last = bool(step) and step["position"] == len(steps)
    new_status = (request.form.get("status") or "").strip()
    if new_status not in ("approved", "rejected"):
        flash("Choose a status: Approved or Rejected.", "error")
        return redirect(url_for("requests.detail", rid=rid))
    if not step or not step["signature_path"]:
        flash(f"Use your signature first — you can only save the status once your signature is under {label}.", "error")
        return redirect(url_for("requests.detail", rid=rid))
    db.execute("UPDATE item_request_steps SET status=? WHERE id=?", (new_status, step["id"]))
    _sync_request_from_steps(db, rid)
    if new_status == "approved" and not is_last:
        # An intermediate approval is logged as an edit ("Step 2
        # (Approved By): Pending → Approved"), because the status line
        # would read "from Pending to Pending", which says nothing happened.
        _log_history(db, rid, g.user, "edit", f"Step {step['position']} ({label})", "Pending", "Approved")
    else:
        _log_history(db, rid, g.user, "status", "Status", STATUS_LABELS.get(req["status"], req["status"]),
                     STATUS_LABELS[new_status])
    log(db, "request_status", f"{req['number']} step {step['position']} -> {new_status}")
    nxt = _current_request_step(db, rid)
    nxt_name = nxt["full_name"] if nxt else ""
    verb = "approved" if new_status == "approved" else "rejected"
    if new_status == "approved" and not is_last:
        notify(db, [nxt["user_id"]] if nxt else [],
               f"{g.user['full_name']} approved Item Request {req['number']} and sent it to you to {REQUEST_STEP_VERBS[nxt['role']]}.",
               url_for("requests.detail", rid=rid), skip=g.user["id"])
        notify(db, [req["owner_id"]],
               f"{g.user['full_name']} approved your Item Request {req['number']} — it is now with {nxt_name}.",
               url_for("requests.detail", rid=rid), skip=g.user["id"])
        for _s in steps:
            if _s["position"] < step["position"] and _s["user_id"] and _s["user_id"] != req["owner_id"]:
                notify(db, [_s["user_id"]],
                       f"{g.user['full_name']} approved Item Request {req['number']} — it is now with {nxt_name}.",
                       url_for("requests.detail", rid=rid), skip=g.user["id"])
        _notify_request_watchers(db, req, rid,
                                 f"{g.user['full_name']} approved Item Request {req['number']} — it is now with {nxt_name}.",
                                 url_for("requests.detail", rid=rid))
    else:
        # A final approval or a rejection: the owner is told directly, and
        # so is everyone who already decided.
        notify(db, [req["owner_id"]],
               f"{g.user['full_name']} {verb} your Item Request {req['number']}.",
               url_for("requests.detail", rid=rid), skip=g.user["id"])
        for _s in steps:
            if _s["position"] < step["position"] and _s["user_id"] and _s["user_id"] != req["owner_id"]:
                notify(db, [_s["user_id"]],
                       f"{g.user['full_name']} {verb} Item Request {req['number']}.",
                       url_for("requests.detail", rid=rid), skip=g.user["id"])
        _notify_request_watchers(db, req, rid,
                                 f"{g.user['full_name']} {verb} Item Request {req['number']}.",
                                 url_for("requests.detail", rid=rid))
    db.commit()
    flash(f"Item Request {verb}.", "ok")
    return redirect(url_for("requests.detail", rid=rid))

def _request_history(db, rid):
    """The edit log for a request, newest first — who changed what and when."""
    return db.execute("SELECT * FROM item_request_history WHERE request_id=? ORDER BY id DESC LIMIT 100", (rid,)).fetchall()

def _log_history(db, rid, user, action, field="", old_value="", new_value=""):
    db.execute("INSERT INTO item_request_history(request_id,user_id,username,full_name,action,field,old_value,new_value) VALUES (?,?,?,?,?,?,?,?)",
               (rid, user["id"], user["username"], user["full_name"], action, field, old_value, new_value))

def _qty_str(v):
    return f"{float(v):g}"

def _line_text(qty, rate, amount, cur):
    return f"{_qty_str(qty)} x {_fmt(rate, cur)} = {_fmt(amount, cur)}"

def _diff_lines(old_lines, new_lines, cur):
    """Field-level changes between the saved lines and the edited lines, as
    (field, old_value, new_value) triples for the edit log. Lines are
    compared by position: a line present in one list only was added or
    removed; a line present in both with different values was changed. The
    field is the line's item name (falling back to its description)."""
    out = []
    n = max(len(old_lines), len(new_lines))
    for i in range(n):
        old = old_lines[i] if i < len(old_lines) else None
        new = new_lines[i] if i < len(new_lines) else None
        if old is None and new is not None:
            out.append((_line_name(new), "", _line_text(new["qty"], new["rate"], new["amount"], cur)))
        elif old is not None and new is None:
            out.append((_line_name(old), _line_text(old["qty"], old["rate"], old["amount"], cur), ""))
        elif old is not None and new is not None:
            if (old["item_name"] or "") != (new["item_name"] or "") or (old["description"] or "") != new["description"] or _money(old["qty"]) != _money(new["qty"]) or _money(old["rate"]) != _money(new["rate"]):
                out.append((_line_name(new), _line_text(old["qty"], old["rate"], old["amount"], cur),
                            _line_text(new["qty"], new["rate"], new["amount"], cur)))
    return out


def _line_name(line):
    """A line's label for the edit log: its item name, else its description."""
    return (line["item_name"] or "").strip() or (line["description"] or "").strip()

def _save_logo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in config.LOGO_EXTENSIONS:
        return None
    folder = os.path.join(config.UPLOAD_DIR, "invoice_logos")
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(10) + "." + ext
    file_storage.save(os.path.join(folder, name))
    return name

def _logo_path(name):
    if not name:
        return None
    p = os.path.join(config.UPLOAD_DIR, "invoice_logos", name)
    return p if os.path.exists(p) else None

def _new_request_code(db):
    for _ in range(200):
        cand = f"HRC-{secrets.randbelow(90000) + 10000}"
        if db.execute("SELECT 1 FROM item_requests WHERE public_code=?", (cand,)).fetchone() is None:
            if db.execute("SELECT 1 FROM invoices WHERE public_code=?", (cand,)).fetchone() is None:
                if db.execute("SELECT 1 FROM public_links WHERE code_text=?", (cand,)).fetchone() is None:
                    if db.execute("SELECT 1 FROM applications WHERE public_code=?", (cand,)).fetchone() is None:
                        if db.execute("SELECT 1 FROM ddb_rows WHERE public_code=?", (cand,)).fetchone() is None:
                            return cand
    return None

def _parse_lines(form):
    lines = []
    names = form.getlist("item_name")
    descs = form.getlist("description")
    qtys = form.getlist("qty")
    rates = form.getlist("rate")
    for i, desc in enumerate(descs):
        name = (names[i] if i < len(names) else "").strip()
        if not (name or (desc or "").strip()):
            continue
        qty = _money(qtys[i]) if i < len(qtys) else Decimal("1")
        rate = _money(rates[i]) if i < len(rates) else Decimal("0")
        # Round figures only: the rate is a whole number, so the amount,
        # subtotal and grand total are whole numbers too.
        rate = rate.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        amount = (qty * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        lines.append({"item_name": name, "description": (desc or "").strip(), "qty": qty, "rate": rate, "amount": amount})
    return lines

def _sigs(form, kind=None):
    sigs = []
    titles = form.getlist("sig_title"); persons = form.getlist("sig_person"); desigs = form.getlist("sig_designation")
    for i in range(len(titles)):
        if (titles[i] or persons[i] or "").strip():
            sigs.append({"title": titles[i].strip(), "person": persons[i].strip(), "designation": desigs[i].strip() if i < len(desigs) else "", "type": "line"})
    if not sigs and kind is not None:
        try:
            sigs = json.loads(kind["signatures_json"] or "[]")
        except Exception:
            sigs = []
    return sigs

def _qr_svg(url):
    return segno.make(url, error="m").svg_inline(scale=4, border=1, dark="#10283a", omitsize=True)

# ---------------------------------------------------------------- list redirect
@bp.route("/requests")
@login_required
def list_requests():
    # The request list lives as a default tab inside Department Database.
    args = {"tab": "requests"}
    if is_portal_admin(g.user):
        args["dept"] = g.user["department_id"]
    return redirect(url_for("ddb.index", **args))

# ---------------------------------------------------------------- kinds (dept admin)
@bp.route("/requests/kinds")
@login_required
def kinds():
    # A department admin sees their own department's kinds; the portal
    # admin and administrative permission users see any department's
    # (with a department switcher) so they can delete a kind from any
    # department.
    if not (_is_dept_admin(g.user) or is_portal_admin(g.user)):
        abort(403)
    db = get_db()
    if is_portal_admin(g.user):
        dept_id = request.args.get("dept", type=int) or g.user["department_id"] or db.execute("SELECT id FROM departments ORDER BY id LIMIT 1").fetchone()["id"]
        depts = db.execute("SELECT id, name FROM departments ORDER BY id").fetchall()
    else:
        dept_id = g.user["department_id"]
        depts = []
    rows = db.execute("SELECT * FROM item_request_kinds WHERE department_id=? AND status != 'deleted' ORDER BY id", (dept_id,)).fetchall()
    # The list shows how many signature blocks the kind still carries.
    # (The template used to render len() of the raw JSON text, which counted
    # characters — '[]' showed as 2. Old kinds keep their stored blocks;
    # new ones carry none.)
    rows = [dict(r, sig_count=len(json.loads(r["signatures_json"] or "[]"))) for r in rows]
    return render_template("request_kinds.html", rows=rows, depts=depts, dept_id=dept_id,
                           can_manage_kinds=(_is_dept_admin(g.user) and g.user["department_id"] == dept_id))

@bp.route("/requests/kinds/delete", methods=["POST"])
@login_required
def kinds_delete():
    """Delete the selected Item Request kinds. A department admin deletes
    only their own department's kinds; the portal admin and administrative
    permission users delete any department's. A deleted kind disappears
    from the list and the picker at once and does not go to the Recycle
    Bin — but the requests already made from it stay exactly as they are:
    their frozen copy keeps working, and the kind row is kept behind the
    scenes for them."""
    db = get_db()
    ids = [int(x) for x in request.form.getlist("kind_ids") if str(x).isdigit()]
    if not ids:
        flash("Select at least one kind to delete.", "error")
        return redirect(url_for("requests.kinds"))
    rows = db.execute("SELECT * FROM item_request_kinds WHERE id IN (%s)" % ",".join("?" * len(ids)), tuple(ids)).fetchall()
    if not rows:
        flash("Those kinds were not found.", "error")
        return redirect(url_for("requests.kinds"))
    for k in rows:
        if not (is_portal_admin(g.user) or (_is_dept_admin(g.user) and k["department_id"] == g.user["department_id"])):
            abort(403)
    db.execute("UPDATE item_request_kinds SET status='deleted' WHERE id IN (%s)" % ",".join("?" * len(ids)), tuple(ids))
    log(db, "request_kind_deleted", f"{len(rows)} kind(s)")
    db.commit()
    flash(f"Deleted {len(rows)} kind{'s' if len(rows) != 1 else ''}. The requests made from them stay as they are.", "ok")
    if is_portal_admin(g.user):
        return redirect(url_for("requests.kinds", dept=rows[0]["department_id"]))
    return redirect(url_for("requests.kinds"))

@bp.route("/requests/kinds/starters", methods=["POST"])
@login_required
def kind_starters():
    _dept_admin_required()
    db = get_db()
    if db.execute("SELECT 1 FROM item_request_kinds WHERE department_id=? AND name=? AND status != 'deleted'", (g.user["department_id"], "Office Supplies Request")).fetchone() is None:
        db.execute("INSERT INTO item_request_kinds(department_id,created_by,name,number_prefix,default_currency,show_amount_in_words,notes,show_company_logo,show_address,company_name,company_address,signatures_json,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (g.user["department_id"], g.user["id"], "Office Supplies Request", "REQ", "BDT", 1,
                    "Items are issued from the store on approval.", 1, 1, "", "",
                    json.dumps([]), "active"))
        log(db, "request_kind_starter", "Office Supplies Request")
    db.commit(); flash("Starter Item Request kind created for your department.", "ok")
    return redirect(url_for("requests.kinds"))

@bp.route("/requests/kinds/new", methods=["GET", "POST"])
@login_required
def kind_new():
    _dept_admin_required()
    db = get_db()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Write a kind name.", "error")
            return render_template("request_kind_form.html", kind=None, sigs=[], currencies=CURRENCIES,
                                   default_company_name=setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME),
                                   default_company_address=config.DEFAULT_COMPANY_ADDRESS)
        left = _save_logo(request.files.get("logo_left")); right = _save_logo(request.files.get("logo_right"))
        sigs = _sigs(request.form)
        kid = db.execute("INSERT INTO item_request_kinds(department_id,created_by,name,number_prefix,default_currency,show_amount_in_words,notes,show_company_logo,show_address,company_name,company_address,logo_left,logo_right,signatures_json,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (g.user["department_id"], g.user["id"], name, (request.form.get("number_prefix") or "REQ").strip().upper()[:10],
                          request.form.get("currency") or "BDT", 1 if request.form.get("amount_in_words") else 0,
                          request.form.get("notes") or "", 1 if request.form.get("show_company_logo") else 0,
                          1 if request.form.get("show_address") else 0, (request.form.get("company_name") or "").strip(),
                          (request.form.get("company_address") or "").strip(), left, right, json.dumps(sigs),
                          "active" if request.form.get("status") != "draft" else "draft")).lastrowid
        log(db, "request_kind_new", name)
        db.commit(); flash("Item Request kind saved.", "ok")
        return redirect(url_for("requests.kinds"))
    return render_template("request_kind_form.html", kind=None, sigs=[], currencies=CURRENCIES,
                           default_company_name=setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME),
                           default_company_address=config.DEFAULT_COMPANY_ADDRESS)

@bp.route("/requests/kinds/<int:kid>/edit", methods=["GET", "POST"])
@login_required
def kind_edit(kid):
    _dept_admin_required()
    db = get_db(); kind = _kind(db, kid)
    if kind["department_id"] != g.user["department_id"]:
        abort(403)
    if request.method == "POST":
        left = _save_logo(request.files.get("logo_left")) or kind["logo_left"]
        right = _save_logo(request.files.get("logo_right")) or kind["logo_right"]
        db.execute("UPDATE item_request_kinds SET name=?,number_prefix=?,default_currency=?,show_amount_in_words=?,notes=?,show_company_logo=?,show_address=?,company_name=?,company_address=?,logo_left=?,logo_right=?,signatures_json=?,status=?,updated_at=datetime('now','localtime') WHERE id=?",
                   ((request.form.get("name") or kind["name"]).strip(), (request.form.get("number_prefix") or kind["number_prefix"]).strip().upper()[:10],
                    request.form.get("currency") or kind["default_currency"], 1 if request.form.get("amount_in_words") else 0,
                    request.form.get("notes") or "", 1 if request.form.get("show_company_logo") else 0,
                    1 if request.form.get("show_address") else 0, (request.form.get("company_name") or "").strip(),
                    (request.form.get("company_address") or "").strip(), left, right, json.dumps(_sigs(request.form, kind)),
                    "active" if request.form.get("status") != "draft" else "draft", kid))
        log(db, "request_kind_edit", kind["name"])
        db.commit(); flash("Item Request kind saved. Changes apply to new requests only; sent requests keep their old format.", "ok")
        return redirect(url_for("requests.kinds"))
    return render_template("request_kind_form.html", kind=kind,
                           sigs=json.loads(kind["signatures_json"] or "[]") if kind["signatures_json"] else [],
                           currencies=CURRENCIES,
                           default_company_name=setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME),
                           default_company_address=config.DEFAULT_COMPANY_ADDRESS)

# ---------------------------------------------------------------- create a request
@bp.route("/requests/new", methods=["GET", "POST"])
@login_required
def request_new():
    db = get_db()
    kind_id = request.values.get("kind", type=int)
    kind = _kind(db, kind_id) if kind_id else None
    if kind is not None and (kind["department_id"] != g.user["department_id"] or kind["status"] != "active"):
        flash("That Item Request kind is not available to you.", "error")
        return redirect(url_for("requests.list_requests"))
    if request.method == "POST" and kind is not None:
        # Who approves it: up to 3 steps, picked here, exactly like an
        # application letter — one step and only one step being
        # "Send/Request To", the person who receives the request. The dept
        # admin no longer sets signatures on the kind.
        chain, chain_err = _parse_request_chain(request.form, _request_chain_people(db, g.user["department_id"]))
        if chain_err:
            flash(chain_err, "error")
            return render_template("request_form.html", kind=kind, currencies=CURRENCIES,
                                   chain_people=_request_chain_people(db, g.user["department_id"]),
                                   chain_depts=_request_chain_depts(db, g.user["department_id"]),
                                   steps=_chain_from_form(request.form))
        else:
            cur = request.form.get("currency") or kind["default_currency"]
            if cur not in CURRENCIES:
                cur = kind["default_currency"]
            lines = _parse_lines(request.form)
            if not lines:
                flash("Add at least one item.", "error")
            else:
                sub = sum((l["amount"] for l in lines), Decimal("0.00"))
                words = amount_in_words(sub, cur) if kind["show_amount_in_words"] else ""
                # The recipient is the Send/Request To step's user.
                recipient_id = next(uid for role, uid in chain if role == "send_to")
                number = f"{kind['number_prefix']}-{kind['next_number']:04d}"
                db.execute("UPDATE item_request_kinds SET next_number=next_number+1 WHERE id=?", (kind["id"],))
                rid = db.execute("INSERT INTO item_requests(department_id,kind_id,owner_id,recipient_id,number,currency,request_date,status,subtotal,total,amount_in_words,notes,signatures_json,kind_snapshot_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (g.user["department_id"], kind["id"], g.user["id"], recipient_id, number, cur,
                                  request.form.get("request_date") or date.today().isoformat(), "pending", float(sub), float(sub), words,
                                  request.form.get("notes") or kind["notes"], "[]",
                                  json.dumps({"name": kind["name"], "number_prefix": kind["number_prefix"],
                                              "logo_left": kind["logo_left"], "logo_right": kind["logo_right"],
                                              "company_name": kind["company_name"], "company_address": kind["company_address"],
                                              "show_address": kind["show_address"], "show_company_logo": kind["show_company_logo"]}))).lastrowid
                _save_request_chain(db, rid, chain)
                for i, l in enumerate(lines):
                    db.execute("INSERT INTO item_request_lines(request_id,position,item_name,description,qty,rate,amount) VALUES (?,?,?,?,?,?,?)",
                               (rid, i, l.get("item_name") or "", l["description"], float(l["qty"]), float(l["rate"]), float(l["amount"])))
                _log_history(db, rid, g.user, "created", "", "", number)
                log(db, "request_new", number)
                # The first person in the chain is told it is with them;
                # the Send/Request To user is told at their turn, not now.
                first = chain[0]
                first_user = db.execute("SELECT full_name FROM users WHERE id=?", (first[1],)).fetchone()
                rec = db.execute("SELECT full_name FROM users WHERE id=?", (recipient_id,)).fetchone()
                notify(db, [first[1]],
                       f"{g.user['full_name']} sent you an Item Request {number} ({kind['name']}) to {REQUEST_STEP_VERBS[first[0]]}.",
                       url_for("requests.detail", rid=rid), skip=g.user["id"])
                # The creator's department admin is told a user in their
                # department sent a request.
                _dept = db.execute("SELECT * FROM departments WHERE id=?", (g.user["department_id"],)).fetchone()
                notify_ddb_task(db, g.user, _dept,
                                f"{g.user['full_name']} sent Item Request {number} ({kind['name']}) to {rec['full_name'] if rec else 'HR & Admin'}.",
                                url_for("requests.detail", rid=rid), skip=first[1])
                db.commit()
                flash(f"Request {number} sent. It is now with {first_user['full_name'] if first_user else 'the first approver'}.", "ok")
                return redirect(url_for("requests.detail", rid=rid))
    return render_template("request_form.html", kind=kind, currencies=CURRENCIES,
                           chain_people=_request_chain_people(db, g.user["department_id"]),
                           chain_depts=_request_chain_depts(db, g.user["department_id"]), steps=[])

# ---------------------------------------------------------------- edit a request
@bp.route("/requests/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def request_edit(rid):
    """Edit a request. Only the owner (the user who made it) and the
    recipient (the HR & Admin user it was sent to) can edit it. The number,
    the date, the kind and the recipient stay the same — only the items
    (description, qty, rate), and the notes can be changed. Saving
    recalculates the totals and the amount in words, writes one edit-log
    entry per changed line (and for the notes), logs the edit in the
    portal Activity log, and notifies the OTHER party (the owner is told
    when the recipient edits, the recipient is told when the owner edits)."""
    db = get_db(); req = _request(db, rid)
    if not _can_edit(db, g.user, req):
        abort(403)
    lines = _lines(db, rid)
    kind = _kind(db, req["kind_id"]) if req["kind_id"] else None
    owner = db.execute("SELECT full_name FROM users WHERE id=?", (req["owner_id"],)).fetchone()
    recipient = db.execute("SELECT full_name FROM users WHERE id=?", (req["recipient_id"],)).fetchone() if req["recipient_id"] else None
    if request.method == "POST":
        new_lines = _parse_lines(request.form)
        if not new_lines:
            flash("Add at least one item.", "error")
            return render_template("request_edit_form.html", req=req, lines=lines, kind=kind,
                                   owner_name=owner["full_name"] if owner else "",
                                   recipient_name=recipient["full_name"] if recipient else "",
                                   currencies=CURRENCIES)
        new_notes = request.form.get("notes") or ""
        cur = req["currency"]
        sub = sum((l["amount"] for l in new_lines), Decimal("0.00"))
        words = amount_in_words(sub, cur) if req["amount_in_words"] else ""
        # The edit log: one entry per changed line, plus one for the notes.
        for field, old_v, new_v in _diff_lines(lines, new_lines, cur):
            _log_history(db, rid, g.user, "edit", field, old_v, new_v)
        if (req["notes"] or "") != new_notes:
            _log_history(db, rid, g.user, "edit", "Notes", req["notes"] or "", new_notes)
        db.execute("DELETE FROM item_request_lines WHERE request_id=?", (rid,))
        for i, l in enumerate(new_lines):
            db.execute("INSERT INTO item_request_lines(request_id,position,item_name,description,qty,rate,amount) VALUES (?,?,?,?,?,?,?)",
                       (rid, i, l.get("item_name") or "", l["description"], float(l["qty"]), float(l["rate"]), float(l["amount"])))
        db.execute("UPDATE item_requests SET notes=?,subtotal=?,total=?,amount_in_words=?,updated_at=datetime('now','localtime') WHERE id=?",
                   (new_notes, float(sub), float(sub), words, rid))
        log(db, "request_edit", req["number"])
        # The other party is told the request was updated.
        if g.user["id"] == req["owner_id"]:
            notify(db, [req["recipient_id"]],
                   f"{g.user['full_name']} updated Item Request {req['number']} sent to you.",
                   url_for("requests.detail", rid=rid), skip=g.user["id"])
        else:
            notify(db, [req["owner_id"]],
                   f"{g.user['full_name']} updated your Item Request {req['number']}.",
                   url_for("requests.detail", rid=rid), skip=g.user["id"])
        # The creator's department admin is told a request from their
        # department was updated. The creator is already told above when the
        # recipient edits, so they are not told twice.
        _dept_admins = [r[0] for r in db.execute(
            "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1",
            (req["department_id"],))]
        notify(db, [uid for uid in _dept_admins if uid != req["owner_id"]],
               f"{g.user['full_name']} updated Item Request {req['number']}.",
               url_for("requests.detail", rid=rid), skip=g.user["id"])
        db.commit()
        flash(f"Request {req['number']} updated. The other party has been notified.", "ok")
        return redirect(url_for("requests.detail", rid=rid))
    return render_template("request_edit_form.html", req=req, lines=lines, kind=kind,
                           owner_name=owner["full_name"] if owner else "",
                           recipient_name=recipient["full_name"] if recipient else "",
                           currencies=CURRENCIES)

# ---------------------------------------------------------------- detail, status, PDF, public QR
@bp.route("/requests/<int:rid>")
@login_required
def detail(rid):
    db = get_db(); req = _request(db, rid)
    if not _can_view(db, g.user, req):
        abort(403)
    lines = _lines(db, rid)
    kind = _kind(db, req["kind_id"]) if req["kind_id"] else None
    owner = db.execute("SELECT full_name FROM users WHERE id=?", (req["owner_id"],)).fetchone()
    recipient = db.execute("SELECT full_name FROM users WHERE id=?", (req["recipient_id"],)).fetchone() if req["recipient_id"] else None
    qr_svg = qr_url = None
    if req["public_code"] and req["public_enabled"]:
        qr_url = external_url(db, "requests.code_page", code=req["public_code"])
        qr_svg = _qr_svg(qr_url)
    return render_template("request_detail.html", req=req, lines=lines, kind=kind,
                           owner_name=owner["full_name"] if owner else "",
                           recipient_name=recipient["full_name"] if recipient else "",
                           qr_svg=qr_svg, qr_url=qr_url,
                           steps=_request_steps(db, rid), step_roles=REQUEST_STEP_ROLES,
                           current_step=_current_request_step(db, rid),
                           can_act=_can_act_request(db, g.user, req),
                           can_status=_can_change_status(db, g.user, req),
                           can_edit=_can_edit(db, g.user, req),
                           can_delete=(is_portal_admin(g.user) or req["owner_id"] == g.user["id"]),
                           can_manage=_can_manage_public(db, g.user, req),
                           history=_request_history(db, rid),
                           statuses=STATUSES, labels=STATUS_LABELS)

@bp.route("/requests/<int:rid>/delete", methods=["POST"])
@login_required
def request_delete(rid):
    """Delete an item request for good. Only the owner, a portal admin or
    an administrative permission user may do it, and only after typing
    their own password in the warning pop-up. The request, its lines,
    its edit history and its chain steps are removed; its number is
    never reused. If the owner deletes it, the department admin is told.
    (Follows the invoice delete exactly: password, hard delete, owner
    deletes -> dept admin told, portal admin deletes -> nobody told.)"""
    from security import reauth_ok
    db = get_db(); req = _request(db, rid)
    if not (req["owner_id"] == g.user["id"] or is_portal_admin(g.user)):
        abort(403)
    if not reauth_ok(g.user, request.form):
        flash("Wrong password. The request was not deleted.", "err")
        return redirect(url_for("requests.detail", rid=rid))
    number = req["number"] or "request"
    dept_id = req["department_id"]
    # The chain steps' signature files are removed too (the step rows go
    # with the request through the foreign key, but the files do not).
    for _s in _request_steps(db, rid):
        if _s["signature_path"]:
            try:
                _f = os.path.join(config.UPLOAD_DIR, "req_signatures", os.path.basename(_s["signature_path"]))
                if os.path.exists(_f):
                    os.remove(_f)
            except Exception:
                pass
    db.execute("DELETE FROM item_request_lines WHERE request_id=?", (rid,))
    db.execute("DELETE FROM item_request_history WHERE request_id=?", (rid,))
    db.execute("DELETE FROM item_request_steps WHERE request_id=?", (rid,))
    db.execute("DELETE FROM item_requests WHERE id=?", (rid,))
    log(db, "item_request_deleted", number)
    # If the owner deletes it, the department admin is told. A portal
    # admin deleting it tells nobody (the watcher rule: nobody is told
    # about a portal admin's own actions).
    if req["owner_id"] == g.user["id"] and not is_portal_admin(g.user):
        notify_ddb_row_task(db, g.user, dept_id,
                            f"{g.user['full_name']} deleted item request {number}.",
                            url_for("ddb.index", dept=dept_id, tab="requests"))
    db.commit()
    flash(f"Item request {number} deleted.", "ok")
    return redirect(url_for("ddb.index", dept=dept_id, tab="requests"))


@bp.route("/requests/<int:rid>/step-signature", methods=["POST"])
@login_required
def request_step_signature(rid):
    return _sign_request_step(rid)

@bp.route("/requests/<int:rid>/decide", methods=["POST"])
@login_required
def request_decide(rid):
    return _decide_request(rid)

@bp.route("/requests/<int:rid>/status", methods=["POST"])
@login_required
def change_status(rid):
    db = get_db(); req = _request(db, rid)
    if not _can_change_status(db, g.user, req):
        abort(403)
    new_status = (request.form.get("status") or "").strip()
    if new_status not in STATUSES:
        flash("Choose a status: Pending, Issued, Paid or Handovered.", "error")
        return redirect(url_for("requests.detail", rid=rid))
    if new_status == req["status"]:
        flash("Status is already " + STATUS_LABELS[new_status] + ".", "ok")
        return redirect(url_for("requests.detail", rid=rid))
    db.execute("UPDATE item_requests SET status=?,updated_at=datetime('now','localtime') WHERE id=?", (new_status, rid))
    log(db, "request_status", f"{req['number']} -> {new_status}")
    # The creator is told the status changed.
    notify(db, [req["owner_id"]],
           f"{g.user['full_name']} changed Item Request {req['number']} to {STATUS_LABELS[new_status]}.",
           url_for("requests.detail", rid=rid), skip=g.user["id"])
    # The creator's department admin is told the request's status changed.
    # The creator is already told above, so they are not told twice.
    _dept_admins = [r[0] for r in db.execute(
        "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1",
        (req["department_id"],))]
    notify(db, [uid for uid in _dept_admins if uid != req["owner_id"]],
           f"{g.user['full_name']} changed Item Request {req['number']} to {STATUS_LABELS[new_status]}.",
           url_for("requests.detail", rid=rid), skip=g.user["id"])
    db.commit()
    flash(f"Status changed to {STATUS_LABELS[new_status]}. The creator has been notified.", "ok")
    return redirect(url_for("requests.detail", rid=rid))

@bp.route("/requests/<int:rid>/pdf")
@login_required
def request_pdf(rid):
    db = get_db(); req = _request(db, rid)
    if not _can_view(db, g.user, req):
        abort(403)
    # ?watermark=0 downloads the PDF without any watermark (no seal, no
    # stamp); the default shows it.
    data = _build_pdf(db, req, hide_watermark=(request.args.get("watermark") == "0"))
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{(req["number"] or "request")}.pdf"'
    return resp

@bp.route("/requests/<int:rid>/public", methods=["POST"])
@login_required
def request_public(rid):
    db = get_db(); req = _request(db, rid)
    if not _can_manage_public(db, g.user, req):
        abort(403)
    action = request.form.get("action", "save")
    if action == "off":
        db.execute("UPDATE item_requests SET public_enabled=0 WHERE id=?", (rid,))
    elif action == "regenerate":
        # new code kills the old printed QR
        db.execute("UPDATE item_requests SET public_code=?,public_enabled=1 WHERE id=?", (_new_request_code(db), rid))
    else:
        code = req["public_code"] or _new_request_code(db)
        db.execute("UPDATE item_requests SET public_code=?,public_enabled=1 WHERE id=?", (code, rid))
    db.commit(); flash("Public QR saved.", "ok"); return redirect(url_for("requests.detail", rid=rid))

@bp.route("/requests/<int:rid>/qr")
@login_required
def request_qr(rid):
    db = get_db(); req = _request(db, rid)
    if not _can_view(db, g.user, req) or not req["public_code"]:
        abort(404)
    url = external_url(db, "requests.code_page", code=req["public_code"])
    item = {"id": req["id"], "title": "Item Request", "dept": req["number"] or "", "svg": _qr_svg(url), "url": url, "code": req["public_code"]}
    return render_template("qr_label.html", items=[item], many=False)

def _public_check(db, req):
    return req is not None and bool(req["public_enabled"])

@bp.route("/requests/code/<code>")
def code_page(code):
    """Public code view: anyone who scans the QR (or types HRC-#####) sees the request and downloads the PDF. No login needed."""
    db = get_db()
    req = db.execute("SELECT * FROM item_requests WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if req is None:
        return render_template("request_code.html", code=code, status="missing", req=None, lines=[]), 404
    if not _public_check(db, req):
        return render_template("request_code.html", code=code, status="off", req=req, lines=[]), 410
    db.execute("UPDATE item_requests SET public_views=public_views+1 WHERE id=?", (req["id"],)); db.commit()
    kind = _kind(db, req["kind_id"]) if req["kind_id"] else None
    owner = db.execute("SELECT full_name FROM users WHERE id=?", (req["owner_id"],)).fetchone()
    recipient = db.execute("SELECT full_name FROM users WHERE id=?", (req["recipient_id"],)).fetchone() if req["recipient_id"] else None
    return render_template("request_code.html", code=code, status="ok", req=req, lines=_lines(db, req["id"]),
                           kind_name=kind["name"] if kind else "", owner_name=owner["full_name"] if owner else "",
                           recipient_name=recipient["full_name"] if recipient else "")

@bp.route("/requests/code/<code>/pdf")
def code_pdf(code):
    db = get_db()
    req = db.execute("SELECT * FROM item_requests WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if req is None or not _public_check(db, req):
        abort(404)
    data = _build_pdf(db, req)
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{code}.pdf"'
    return resp

def _build_pdf(db, req, hide_watermark=False):
    lines = _lines(db, req["id"])
    try:
        snap = json.loads(req["kind_snapshot_json"] or "{}")
    except Exception:
        snap = {}
    company = snap.get("company_name") or setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME)
    address = snap.get("company_address") or config.DEFAULT_COMPANY_ADDRESS
    show_address = snap.get("show_address", 1)
    owner = db.execute("SELECT full_name, designation FROM users WHERE id=?", (req["owner_id"],)).fetchone()
    recipient = db.execute("SELECT full_name FROM users WHERE id=?", (req["recipient_id"],)).fetchone() if req["recipient_id"] else None
    dept = db.execute("SELECT name FROM departments WHERE id=?", (req["department_id"],)).fetchone()
    # Signatures: a chained request shows the owner's block (Requested By)
    # plus one block per chain step, each with the step's saved signature
    # image, the role label ("Rejected By" when that step rejected), the
    # name, the designation and the department. An older request keeps
    # exactly what it had: the kind's signatures as text.
    steps = _request_steps(db, req["id"])
    if steps:
        sig_rows = [("Requested By", owner["full_name"] if owner else "", owner["designation"] if owner else "")]
        for s in steps:
            label = "Rejected By" if s["status"] == "rejected" else REQUEST_STEP_ROLES.get(s["role"], s["role"])
            img = os.path.join(config.UPLOAD_DIR, "req_signatures", os.path.basename(s["signature_path"])) if s["signature_path"] else None
            sig_rows.append((label, s["full_name"] or "", s["designation"] or "", s["dept_name"] or "", img))
    else:
        try:
            sigs = json.loads(req["signatures_json"] or "[]")
        except Exception:
            sigs = []
        sig_rows = []
        for s in sigs:
            # The owner's (creator's) designation comes from their user account
            # when the kind left it blank — the same as the invoice Prepared By.
            desig = s.get("designation") or ""
            if not desig.strip() and "request" in (s.get("title") or "").lower():
                desig = owner["designation"] if owner else ""
            sig_rows.append((s.get("title") or "", s.get("person") or "", desig))
    # Meta: Date and Status on the right; Request No., Requested by,
    # Department and Requested to stacked on the left.
    meta_left = []
    if req["number"]:
        meta_left.append(("REQUEST NO.", req["number"]))
    meta_left.append(("Requested by", owner["full_name"] if owner else ""))
    meta_left.append(("Department", dept["name"] if dept else ""))
    meta_left.append(("Requested to", (recipient["full_name"] + " (HR & Admin)") if recipient else ""))
    meta_right = []
    if req["request_date"]:
        meta_right.append(("DATE", req["request_date"]))
    meta_right.append(("STATUS", STATUS_LABELS.get(req["status"], req["status"].title())))
    rows = [[str(i), l["item_name"] or "", l["description"] or "", str(l["qty"]), _fmt(l["rate"], req["currency"]), _fmt(l["amount"], req["currency"])]
            for i, l in enumerate(lines, start=1)]
    totals = [("Subtotal", _fmt(req["subtotal"], req["currency"])), ("Grand total", _fmt(req["total"], req["currency"]))]
    qr_url = external_url(db, "requests.code_page", code=req["public_code"]) if req["public_code"] else ""
    return exports.request_pdf(
        meta_left=meta_left, meta_right=meta_right,
        cols=["#", "Item name", "Description", "Qty", "Rate", "Amount"], rows=rows, totals=totals,
        words=(req["amount_in_words"] or ""), terms=req["notes"] or "", sigs=sig_rows,
        code=req["public_code"] if req["public_enabled"] else "",
        company=company, company_address=address, show_address=bool(show_address),
        logo_left=_logo_path(snap.get("logo_left")), logo_right=_logo_path(snap.get("logo_right")),
        qr_url=qr_url, is_approved=(req["status"] == "approved"), is_rejected=(req["status"] == "rejected"),
        hide_watermark=hide_watermark)
