"""
routes_requests.py - Item Requests (NEW in this version, section 49 in README).

A default "Request items" tab inside Department Database (like Invoices).
A dept admin makes an Item Request kind for their OWN department (like an
invoice template). A user picks a kind in the Request items tab, fills in
the items, and sends the request to a SPECIFIC user — who must be a user in
the HR & Admin Department. The recipient is notified, sees the request in
their "Other's request" sub-tab, and can print it, download its PDF, and
change its status: Pending -> Issued -> Paid -> Handovered. A new request
starts as Pending. When the recipient changes the status, the creator is
notified and can see the new status in "My request".

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
from decimal import Decimal, InvalidOperation

import segno
from flask import (Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for)

import config
import exports
from auth import login_required
from utils import is_portal_admin
from core import notify
from models import get_db, log, setting_get

bp = Blueprint("requests", __name__)
CURRENCIES = ["BDT", "USD", "EUR", "GBP", "INR"]
STATUSES = ["pending", "issued", "paid", "handovered"]
STATUS_LABELS = {"pending": "Pending", "issued": "Issued", "paid": "Paid", "handovered": "Handovered"}

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
    return f"{word} {_words(whole)} Only"

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
    return False

def _can_change_status(db, user, req):
    """Only the recipient (the HR & Admin user the request was sent to) changes the status."""
    return req["recipient_id"] == user["id"]

def _can_manage_public(db, user, req):
    return (is_portal_admin(user) or req["owner_id"] == user["id"] or req["recipient_id"] == user["id"]
            or (_is_dept_admin(user) and req["department_id"] == user["department_id"]))

def _lines(db, rid):
    return db.execute("SELECT * FROM item_request_lines WHERE request_id=? ORDER BY position, id", (rid,)).fetchall()

def _can_edit(db, user, req):
    """Both the owner (the user who made the request) and the recipient (the
    HR & Admin user it was sent to) can edit the request record. Nobody else
    — not the portal admin, not other users in the department — can edit it."""
    return req["owner_id"] == user["id"] or req["recipient_id"] == user["id"]

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
    removed; a line present in both with different values was changed."""
    out = []
    n = max(len(old_lines), len(new_lines))
    for i in range(n):
        old = old_lines[i] if i < len(old_lines) else None
        new = new_lines[i] if i < len(new_lines) else None
        if old is None and new is not None:
            out.append((new["description"], "", _line_text(new["qty"], new["rate"], new["amount"], cur)))
        elif old is not None and new is None:
            out.append((old["description"] or "", _line_text(old["qty"], old["rate"], old["amount"], cur), ""))
        elif old is not None and new is not None:
            if (old["description"] or "") != new["description"] or _money(old["qty"]) != _money(new["qty"]) or _money(old["rate"]) != _money(new["rate"]):
                out.append((new["description"], _line_text(old["qty"], old["rate"], old["amount"], cur),
                            _line_text(new["qty"], new["rate"], new["amount"], cur)))
    return out

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
                    return cand
    return None

def _parse_lines(form):
    lines = []
    descs = form.getlist("description")
    qtys = form.getlist("qty")
    rates = form.getlist("rate")
    for i, desc in enumerate(descs):
        if not (desc or "").strip():
            continue
        qty = _money(qtys[i]) if i < len(qtys) else Decimal("1")
        rate = _money(rates[i]) if i < len(rates) else Decimal("0")
        lines.append({"description": desc.strip(), "qty": qty, "rate": rate, "amount": qty * rate})
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
    _dept_admin_required()
    db = get_db()
    rows = db.execute("SELECT * FROM item_request_kinds WHERE department_id=? ORDER BY id", (g.user["department_id"],)).fetchall()
    return render_template("request_kinds.html", rows=rows)

@bp.route("/requests/kinds/starters", methods=["POST"])
@login_required
def kind_starters():
    _dept_admin_required()
    db = get_db()
    if db.execute("SELECT 1 FROM item_request_kinds WHERE department_id=? AND name=?", (g.user["department_id"], "Office Supplies Request")).fetchone() is None:
        db.execute("INSERT INTO item_request_kinds(department_id,created_by,name,number_prefix,default_currency,show_amount_in_words,notes,show_company_logo,show_address,company_name,company_address,signatures_json,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (g.user["department_id"], g.user["id"], "Office Supplies Request", "REQ", "BDT", 1,
                    "Items are issued from the store on approval.", 1, 1, "", "",
                    json.dumps([{"title": "Requested by", "person": "", "designation": ""},
                                {"title": "Received by", "person": "", "designation": ""},
                                {"title": "Approved by", "person": "", "designation": ""}]), "active"))
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
    recipients = hr_admin_users(db)
    if request.method == "POST" and kind is not None:
        # The recipient must be an HR & Admin Department user — never anyone else.
        try:
            recipient_id = int(request.form.get("recipient_id") or 0)
        except ValueError:
            recipient_id = 0
        if recipient_id not in [r["id"] for r in recipients]:
            flash("Choose a recipient from the HR & Admin Department.", "error")
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
                sigs = _sigs(request.form, kind)
                # Fill the two named signatures from the people involved, when the kind left them blank.
                for s in sigs:
                    t = (s.get("title") or "").lower()
                    if not (s.get("person") or "").strip() and "request" in t:
                        s["person"] = g.user["full_name"]
                    elif not (s.get("person") or "").strip() and "receiv" in t:
                        rec = db.execute("SELECT full_name FROM users WHERE id=?", (recipient_id,)).fetchone()
                        s["person"] = rec["full_name"] if rec else ""
                number = f"{kind['number_prefix']}-{kind['next_number']:04d}"
                db.execute("UPDATE item_request_kinds SET next_number=next_number+1 WHERE id=?", (kind["id"],))
                rid = db.execute("INSERT INTO item_requests(department_id,kind_id,owner_id,recipient_id,number,currency,request_date,status,subtotal,total,amount_in_words,notes,signatures_json,kind_snapshot_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (g.user["department_id"], kind["id"], g.user["id"], recipient_id, number, cur,
                                  request.form.get("request_date") or date.today().isoformat(), "pending", float(sub), float(sub), words,
                                  request.form.get("notes") or kind["notes"], json.dumps(sigs),
                                  json.dumps({"name": kind["name"], "number_prefix": kind["number_prefix"],
                                              "logo_left": kind["logo_left"], "logo_right": kind["logo_right"],
                                              "company_name": kind["company_name"], "company_address": kind["company_address"],
                                              "show_address": kind["show_address"], "show_company_logo": kind["show_company_logo"]}))).lastrowid
                for i, l in enumerate(lines):
                    db.execute("INSERT INTO item_request_lines(request_id,position,description,qty,rate,amount) VALUES (?,?,?,?,?,?)",
                               (rid, i, l["description"], float(l["qty"]), float(l["rate"]), float(l["amount"])))
                _log_history(db, rid, g.user, "created", "", "", number)
                rec = db.execute("SELECT full_name FROM users WHERE id=?", (recipient_id,)).fetchone()
                log(db, "request_new", number)
                notify(db, [recipient_id],
                       f"{g.user['full_name']} sent you an Item Request {number} ({kind['name']}).",
                       url_for("requests.detail", rid=rid), skip=g.user["id"])
                db.commit()
                flash(f"Request {number} sent to {rec['full_name'] if rec else 'HR & Admin'}.", "ok")
                return redirect(url_for("requests.detail", rid=rid))
    return render_template("request_form.html", kind=kind, recipients=recipients, sigs=json.loads(kind["signatures_json"] or "[]") if kind else [], currencies=CURRENCIES)

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
            db.execute("INSERT INTO item_request_lines(request_id,position,description,qty,rate,amount) VALUES (?,?,?,?,?,?)",
                       (rid, i, l["description"], float(l["qty"]), float(l["rate"]), float(l["amount"])))
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
        qr_url = url_for("requests.code_page", code=req["public_code"], _external=True)
        qr_svg = _qr_svg(qr_url)
    return render_template("request_detail.html", req=req, lines=lines, kind=kind,
                           owner_name=owner["full_name"] if owner else "",
                           recipient_name=recipient["full_name"] if recipient else "",
                           qr_svg=qr_svg, qr_url=qr_url,
                           can_status=_can_change_status(db, g.user, req),
                           can_edit=_can_edit(db, g.user, req),
                           can_manage=_can_manage_public(db, g.user, req),
                           history=_request_history(db, rid),
                           statuses=STATUSES, labels=STATUS_LABELS)

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
    db.commit()
    flash(f"Status changed to {STATUS_LABELS[new_status]}. The creator has been notified.", "ok")
    return redirect(url_for("requests.detail", rid=rid))

@bp.route("/requests/<int:rid>/pdf")
@login_required
def request_pdf(rid):
    db = get_db(); req = _request(db, rid)
    if not _can_view(db, g.user, req):
        abort(403)
    data = _build_pdf(db, req)
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
    url = url_for("requests.code_page", code=req["public_code"], _external=True)
    item = {"id": req["id"], "title": "Item Request", "dept": req["number"] or "", "svg": _qr_svg(url), "url": url, "code": req["public_code"]}
    return render_template("qr_label.html", items=[item], many=False)

def _public_check(db, req):
    return req is not None and bool(req["public_enabled"])

@bp.route("/requests/code/<code>")
@login_required
def code_page(code):
    """Login-only code view: a logged-in user types HRC-#####, sees the request, downloads the PDF."""
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
@login_required
def code_pdf(code):
    db = get_db()
    req = db.execute("SELECT * FROM item_requests WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if req is None or not _public_check(db, req):
        abort(404)
    data = _build_pdf(db, req)
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{code}.pdf"'
    return resp

def _build_pdf(db, req):
    lines = _lines(db, req["id"])
    try:
        snap = json.loads(req["kind_snapshot_json"] or "{}")
    except Exception:
        snap = {}
    company = snap.get("company_name") or setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME)
    address = snap.get("company_address") or config.DEFAULT_COMPANY_ADDRESS
    show_address = snap.get("show_address", 1)
    owner = db.execute("SELECT full_name FROM users WHERE id=?", (req["owner_id"],)).fetchone()
    recipient = db.execute("SELECT full_name FROM users WHERE id=?", (req["recipient_id"],)).fetchone() if req["recipient_id"] else None
    dept = db.execute("SELECT name FROM departments WHERE id=?", (req["department_id"],)).fetchone()
    try:
        sigs = json.loads(req["signatures_json"] or "[]")
    except Exception:
        sigs = []
    sig_rows = []
    for s in sigs:
        sig_rows.append((s.get("title") or "", s.get("person") or "", s.get("designation") or ""))
    meta_left = []
    if req["number"]:
        meta_left.append(("REQUEST NO.", req["number"]))
    if req["request_date"]:
        meta_left.append(("DATE", req["request_date"]))
    meta_left.append(("STATUS", STATUS_LABELS.get(req["status"], req["status"].title())))
    meta_right = [("Requested by", owner["full_name"] if owner else ""),
                  ("Department", dept["name"] if dept else ""),
                  ("Requested to", (recipient["full_name"] + " (HR & Admin)") if recipient else "")]
    rows = [[str(i), l["description"] or "", str(l["qty"]), _fmt(l["rate"], req["currency"]), _fmt(l["amount"], req["currency"])]
            for i, l in enumerate(lines, start=1)]
    totals = [("Subtotal", _fmt(req["subtotal"], req["currency"])), ("Grand total", _fmt(req["total"], req["currency"]))]
    return exports.request_pdf(
        meta_left=meta_left, meta_right=meta_right,
        cols=["#", "Item / Description", "Qty", "Rate", "Amount"], rows=rows, totals=totals,
        words=(req["amount_in_words"] or ""), terms=req["notes"] or "", sigs=sig_rows,
        code=req["public_code"] if req["public_enabled"] else "",
        company=company, company_address=address, show_address=bool(show_address),
        logo_left=_logo_path(snap.get("logo_left")), logo_right=_logo_path(snap.get("logo_right")))
