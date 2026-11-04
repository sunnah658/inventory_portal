"""
routes_invoices.py - Invoices (NEW in this version, section 20 in README).

Dept admin creates invoice templates for their OWN department (not the portal admin).
Employees choose a template in the Invoices tab, fill it, save as Draft, then
Finalize and number it. Finalized invoices are locked: they can be marked Paid or
Voided (with a reason, number kept, never reused), never quietly edited.

Public QR for invoices: HRC- + random 5-digit code, e.g. HRC-48392. The same
random-code system is used for all public QRs (see core.display_code).
Searching a code, viewing it and downloading its PDF all need a login.
A new scan link kills the old code. Draft / Void / switched-off / expired codes
show nothing to download. Watermark is OFF by default; the template can turn it
on and type what it will be. Currency sits beside every amount; one invoice has
one currency, no auto-conversion. Two logos (left + right top corner) are optional.

Dept-admin sharing: (1) a dept admin can share a template with another dept admin,
who can then Use it in their own department (a copy; the original is unchanged,
revocable). (2) a dept admin can share their department's invoices, view-only,
with another dept admin (separate share, revocable, with expiry).

Used by: app.py (registers it). Uses: core.py, auth.py, models.py, exports.py, config.py
Templates: invoice_*.html
"""
import io
import json
import os
import re
import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import segno
from flask import (Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for)

import config
import exports
from auth import login_required
from core import display_code, new_random_code_text
from models import get_db, log, setting_get

bp = Blueprint("invoices", __name__)
CURRENCIES = ["BDT", "USD", "EUR", "GBP", "INR"]
KIND_COLOURS = {"billing": "#0F7CA6", "admin": "#7C5CBF", "conveyance": "#1E8A5A", "custom": "#D97A1A"}
KIND_TITLES = {"billing": "INVOICE", "admin": "EXPENSE VOUCHER", "conveyance": "CONVEYANCE BILL", "custom": "PURCHASE REQUEST"}
STARTERS = [
    {"name": "Billing Invoice", "kind": "billing", "title": "INVOICE", "subtitle": "Original for customer", "prefix": "BIL", "vat": 5,
     "notes": "Payment within 15 days. Bank: City Bank, A/C 1234567890.",
     "cols": "Description · Qty · Rate · Amount", "top": "Invoice date, Bill to (customer name), Customer address, Reference / PO number, Department"},
    {"name": "Admin Expense Voucher", "kind": "admin", "title": "EXPENSE VOUCHER", "subtitle": "Office expense voucher", "prefix": "ADM", "vat": 0,
     "notes": "Bills attached. Reimbursement within 7 working days.",
     "cols": "Item · Purpose · Amount", "top": "Invoice date, Employee, Department, Purpose"},
    {"name": "Conveyance Bill", "kind": "conveyance", "title": "CONVEYANCE BILL", "subtitle": "Employee travel claim", "prefix": "CNV", "vat": 0,
     "notes": "Attach rickshaw / CNG slips where available.",
     "cols": "Date · From · To · Mode · Purpose · Amount", "top": "Employee, Employee ID, Department, Period"},
    {"name": "Purchase Request", "kind": "custom", "title": "PURCHASE REQUEST", "subtitle": "Custom format", "prefix": "PRQ", "vat": 0,
     "notes": "Purchase subject to dept admin approval. Quotations attached.",
     "cols": "Item · Spec · Qty · Est. cost", "top": "Requested by, Department, Date, Needed by"},
]

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

def _template(db, tid):
    row = db.execute("SELECT * FROM invoice_templates WHERE id=?", (tid,)).fetchone()
    if row is None:
        abort(404)
    return row

def _invoice(db, iid):
    row = db.execute("SELECT * FROM invoices WHERE id=?", (iid,)).fetchone()
    if row is None:
        abort(404)
    return row

def _shared_dept_ids(db, user):
    """Departments whose invoices this user may view (dept-admin share, view-only)."""
    if not _is_dept_admin(user):
        return []
    rows = db.execute("SELECT from_department_id FROM invoice_dept_shares WHERE to_department_id=? AND revoked=0 "
                      "AND (expires IS NULL OR expires='' OR expires >= date('now','localtime'))",
                      (user["department_id"],)).fetchall()
    return [r[0] for r in rows]

def _can_view(db, user, inv):
    if user["role"] == "admin":
        return True
    if inv["owner_id"] == user["id"]:
        return True
    # Department Database Invoices tab: every user in the same department can
    # SEE every invoice in that department (view only — editing, Paid/Void
    # and public-QR management keep their old owner / dept-admin rules).
    if user["department_id"] == inv["department_id"]:
        return True
    if _is_dept_admin(user) and inv["department_id"] == user["department_id"]:
        return True
    if _is_dept_admin(user) and inv["department_id"] in _shared_dept_ids(db, user):
        return True
    return False

def _can_manage_public(db, user, inv):
    return user["role"] == "admin" or inv["owner_id"] == user["id"] or (_is_dept_admin(user) and inv["department_id"] == user["department_id"])

def _lines(db, iid):
    return db.execute("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY position, id", (iid,)).fetchall()

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

def _new_invoice_code(db):
    for _ in range(200):
        cand = f"HRC-{secrets.randbelow(90000) + 10000}"
        if db.execute("SELECT 1 FROM invoices WHERE public_code=?", (cand,)).fetchone() is None:
            if db.execute("SELECT 1 FROM public_links WHERE code_text=?", (cand,)).fetchone() is None:
                return cand
    return None

def _parse_lines(form, kind):
    lines = []
    descs = form.getlist("description")
    for i, desc in enumerate(descs):
        if not (desc or "").strip() and kind != "conveyance":
            continue
        qty = _money(form.getlist("qty")[i]) if i < len(form.getlist("qty")) else Decimal("1")
        rate = _money(form.getlist("rate")[i]) if i < len(form.getlist("rate")) else Decimal("0")
        amt = _money(form.getlist("amount")[i]) if i < len(form.getlist("amount")) else Decimal("0")
        if kind == "conveyance":
            amt = _money(form.getlist("amount")[i]) if i < len(form.getlist("amount")) else Decimal("0")
            lines.append({"description": desc.strip(), "qty": Decimal("1"), "rate": amt, "amount": amt,
                          "line_date": (form.getlist("line_date")[i] if i < len(form.getlist("line_date")) else ""),
                          "from_place": (form.getlist("from_place")[i] if i < len(form.getlist("from_place")) else ""),
                          "to_place": (form.getlist("to_place")[i] if i < len(form.getlist("to_place")) else ""),
                          "mode": (form.getlist("mode")[i] if i < len(form.getlist("mode")) else ""),
                          "purpose": (form.getlist("purpose")[i] if i < len(form.getlist("purpose")) else ""), "spec": ""})
        elif kind == "custom":
            lines.append({"description": desc.strip(), "qty": qty, "rate": amt, "amount": amt,
                          "spec": (form.getlist("spec")[i] if i < len(form.getlist("spec")) else ""), "line_date": "", "from_place": "", "to_place": "", "mode": "", "purpose": ""})
        elif kind == "admin":
            lines.append({"description": desc.strip(), "qty": Decimal("1"), "rate": amt, "amount": amt,
                          "purpose": (form.getlist("purpose")[i] if i < len(form.getlist("purpose")) else ""), "line_date": "", "from_place": "", "to_place": "", "mode": "", "spec": ""})
        else:
            lines.append({"description": desc.strip(), "qty": qty, "rate": rate, "amount": qty * rate,
                          "line_date": "", "from_place": "", "to_place": "", "mode": "", "purpose": "", "spec": ""})
    return lines

def _totals(lines, vat_pct):
    sub = sum((l["amount"] for l in lines), Decimal("0.00"))
    vat = (sub * Decimal(str(vat_pct)) / Decimal("100")).quantize(Decimal("0.01")) if vat_pct else Decimal("0.00")
    return sub, vat, sub + vat

def _qr_svg(url):
    return segno.make(url, error="m").svg_inline(scale=4, border=1, dark="#10283a", omitsize=True)

def _sigs(form, template=None):
    sigs = []
    titles = form.getlist("sig_title"); persons = form.getlist("sig_person"); desigs = form.getlist("sig_designation")
    for i in range(len(titles)):
        if (titles[i] or persons[i] or "").strip():
            sigs.append({"title": titles[i].strip(), "person": persons[i].strip(), "designation": desigs[i].strip() if i < len(desigs) else "", "type": "line"})
    if not sigs and template is not None:
        try:
            sigs = json.loads(template["signatures_json"] or "[]")
        except Exception:
            sigs = []
    return sigs

# ---------------------------------------------------------------- list / detail
@bp.route("/invoices")
@login_required
def list_invoices():
    # The invoice page now lives as a default tab inside Department Database.
    # Old links and bookmarks keep working through this redirect.
    args = {"tab": "invoices"}
    if g.user["role"] == "admin":
        args["dept"] = g.user["department_id"]
    return redirect(url_for("ddb.index", **args))
@bp.route("/invoices/dept")
@login_required
def dept_list():
    if not (_is_dept_admin(g.user) or g.user["role"] == "admin"):
        abort(403)
    db = get_db()
    dept_id = g.user["department_id"] if g.user["role"] != "admin" else (request.args.get("dept", type=int) or g.user["department_id"])
    rows = db.execute("SELECT i.*, t.name AS template_name, u.full_name AS owner_name FROM invoices i "
                      "LEFT JOIN invoice_templates t ON t.id=i.template_id LEFT JOIN users u ON u.id=i.owner_id "
                      "WHERE i.department_id=? ORDER BY i.id DESC", (dept_id,)).fetchall()
    dept = db.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone()
    return render_template("invoice_dept_list.html", rows=rows, dept=dept)

@bp.route("/invoices/shared")
@login_required
def shared_list():
    if not _is_dept_admin(g.user):
        abort(403)
    db = get_db()
    ids = _shared_dept_ids(db, g.user)
    rows = []
    if ids:
        q = ",".join("?" * len(ids))
        rows = db.execute(f"SELECT i.*, t.name AS template_name, u.full_name AS owner_name, d.name AS dept_name FROM invoices i "
                          f"LEFT JOIN invoice_templates t ON t.id=i.template_id LEFT JOIN users u ON u.id=i.owner_id LEFT JOIN departments d ON d.id=i.department_id "
                          f"WHERE i.department_id IN ({q}) ORDER BY i.id DESC", ids).fetchall()
    return render_template("invoice_shared_list.html", rows=rows)

# ---------------------------------------------------------------- templates
@bp.route("/invoices/templates")
@login_required
def templates():
    _dept_admin_required()
    db = get_db()
    rows = db.execute("SELECT * FROM invoice_templates WHERE department_id=? ORDER BY id", (g.user["department_id"],)).fetchall()
    shared = db.execute("SELECT s.*, t.name AS template_name, t.kind AS kind, d.name AS from_dept FROM invoice_template_shares s "
                        "JOIN invoice_templates t ON t.id=s.template_id JOIN departments d ON d.id=s.from_department_id "
                        "WHERE s.to_department_id=? AND s.revoked=0 AND (s.expires IS NULL OR s.expires='' OR s.expires >= date('now','localtime')) ORDER BY s.id DESC",
                        (g.user["department_id"],)).fetchall()
    return render_template("invoice_templates.html", rows=rows, shared=shared, colours=KIND_COLOURS)

@bp.route("/invoices/templates/starters", methods=["POST"])
@login_required
def starters():
    _dept_admin_required()
    db = get_db()
    for s in STARTERS:
        if db.execute("SELECT 1 FROM invoice_templates WHERE department_id=? AND name=?", (g.user["department_id"], s["name"])).fetchone():
            continue
        db.execute("INSERT INTO invoice_templates(department_id,created_by,name,kind,title,subtitle,number_prefix,default_currency,vat_percent,notes,item_columns_json,top_fields_json,signatures_json,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (g.user["department_id"], g.user["id"], s["name"], s["kind"], s["title"], s["subtitle"], s["prefix"], "BDT", s["vat"], s["notes"], s["cols"], s["top"], json.dumps([{"title": "Authorized by", "person": "", "designation": ""}, {"title": "Approved by", "person": "", "designation": ""}]), "active"))
    log(db, "invoice_starters", f"dept {g.user['department_id']}")
    db.commit(); flash("Starter templates created for your department.", "ok")
    return redirect(url_for("invoices.templates"))

@bp.route("/invoices/templates/new", methods=["GET", "POST"])
@login_required
def template_new():
    _dept_admin_required()
    db = get_db()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Write a template name.", "error"); return render_template("invoice_template_form.html", tpl=None, currencies=CURRENCIES)
        left = _save_logo(request.files.get("logo_left")); right = _save_logo(request.files.get("logo_right"))
        sigs = _sigs(request.form)
        tid = db.execute("INSERT INTO invoice_templates(department_id,created_by,name,kind,title,subtitle,number_prefix,default_currency,vat_percent,show_amount_in_words,notes,show_company_logo,show_address,logo_left,logo_right,watermark_on,watermark_text,signatures_json,item_columns_json,top_fields_json,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (g.user["department_id"], g.user["id"], name, request.form.get("kind") or "billing", (request.form.get("title") or "INVOICE").strip(), (request.form.get("subtitle") or "").strip(),
                          (request.form.get("number_prefix") or "BIL").strip().upper()[:10], request.form.get("currency") or "BDT", float(request.form.get("vat") or 0),
                          1 if request.form.get("amount_in_words") else 0, request.form.get("notes") or "",
                          1 if request.form.get("show_company_logo") else 0, 1 if request.form.get("show_address") else 0, left, right,
                          1 if request.form.get("watermark_on") else 0, (request.form.get("watermark_text") or "").strip()[:50],
                          json.dumps(sigs), request.form.get("item_columns") or "", request.form.get("top_fields") or "", "active" if request.form.get("status") != "draft" else "draft")).lastrowid
        log(db, "invoice_template_new", name); db.commit(); flash("Template saved.", "ok")
        return redirect(url_for("invoices.templates"))
    return render_template("invoice_template_form.html", tpl=None, sigs=[], currencies=CURRENCIES)

@bp.route("/invoices/templates/<int:tid>/edit", methods=["GET", "POST"])
@login_required
def template_edit(tid):
    _dept_admin_required()
    db = get_db(); tpl = _template(db, tid)
    if tpl["department_id"] != g.user["department_id"]:
        abort(403)
    if request.method == "POST":
        left = _save_logo(request.files.get("logo_left")) or tpl["logo_left"]
        right = _save_logo(request.files.get("logo_right")) or tpl["logo_right"]
        db.execute("UPDATE invoice_templates SET name=?,kind=?,title=?,subtitle=?,number_prefix=?,default_currency=?,vat_percent=?,show_amount_in_words=?,notes=?,show_company_logo=?,show_address=?,logo_left=?,logo_right=?,watermark_on=?,watermark_text=?,signatures_json=?,item_columns_json=?,top_fields_json=?,status=?,updated_at=datetime('now','localtime') WHERE id=?",
                   ((request.form.get("name") or tpl["name"]).strip(), request.form.get("kind") or tpl["kind"], (request.form.get("title") or "INVOICE").strip(), (request.form.get("subtitle") or "").strip(),
                    (request.form.get("number_prefix") or tpl["number_prefix"]).strip().upper()[:10], request.form.get("currency") or tpl["default_currency"], float(request.form.get("vat") or 0),
                    1 if request.form.get("amount_in_words") else 0, request.form.get("notes") or "",
                    1 if request.form.get("show_company_logo") else 0, 1 if request.form.get("show_address") else 0, left, right,
                    1 if request.form.get("watermark_on") else 0, (request.form.get("watermark_text") or "").strip()[:50],
                    json.dumps(_sigs(request.form, tpl)), request.form.get("item_columns") or "", request.form.get("top_fields") or "",
                    "active" if request.form.get("status") != "draft" else "draft", tid))
        log(db, "invoice_template_edit", tpl["name"]); db.commit(); flash("Template saved. Changes apply to new invoices only; issued invoices keep their old format.", "ok")
        return redirect(url_for("invoices.templates"))
    return render_template("invoice_template_form.html", tpl=tpl, sigs=json.loads(tpl["signatures_json"] or "[]") if tpl["signatures_json"] else [], currencies=CURRENCIES)

@bp.route("/invoices/templates/<int:tid>/share", methods=["GET", "POST"])
@login_required
def template_share(tid):
    _dept_admin_required()
    db = get_db(); tpl = _template(db, tid)
    if tpl["department_id"] != g.user["department_id"]:
        abort(403)
    depts = db.execute("SELECT * FROM departments WHERE id != ? ORDER BY name", (g.user["department_id"],)).fetchall()
    if request.method == "POST":
        to_dept = int(request.form.get("to_department") or 0)
        if not to_dept or to_dept == g.user["department_id"]:
            flash("Choose another department.", "error")
        else:
            db.execute("INSERT INTO invoice_template_shares(template_id,from_department_id,to_department_id,shared_by,expires) VALUES (?,?,?,?,?)",
                       (tid, g.user["department_id"], to_dept, g.user["id"], request.form.get("expires") or None))
            log(db, "invoice_template_share", f"{tpl['name']} -> dept {to_dept}"); db.commit(); flash("Template shared. The other dept admin can now use it in their department.", "ok")
            return redirect(url_for("invoices.templates"))
    shares = db.execute("SELECT s.*, d.name AS to_dept FROM invoice_template_shares s JOIN departments d ON d.id=s.to_department_id WHERE s.template_id=? ORDER BY s.id DESC", (tid,)).fetchall()
    return render_template("invoice_template_share.html", tpl=tpl, depts=depts, shares=shares)

@bp.route("/invoices/templates/shares/<int:sid>/revoke", methods=["POST"])
@login_required
def template_share_revoke(sid):
    _dept_admin_required()
    db = get_db()
    db.execute("UPDATE invoice_template_shares SET revoked=1 WHERE id=? AND from_department_id=?", (sid, g.user["department_id"]))
    db.commit(); flash("Share revoked.", "ok"); return redirect(url_for("invoices.templates"))

@bp.route("/invoices/templates/shares/<int:sid>/use", methods=["POST"])
@login_required
def template_share_use(sid):
    _dept_admin_required()
    db = get_db()
    share = db.execute("SELECT * FROM invoice_template_shares WHERE id=? AND to_department_id=? AND revoked=0", (sid, g.user["department_id"])).fetchone()
    if share is None:
        abort(404)
    tpl = _template(db, share["template_id"])
    db.execute("INSERT INTO invoice_templates(department_id,created_by,name,kind,title,subtitle,number_prefix,default_currency,vat_percent,show_amount_in_words,notes,show_company_logo,show_address,logo_left,logo_right,watermark_on,watermark_text,signatures_json,item_columns_json,top_fields_json,status,shared_from_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (g.user["department_id"], g.user["id"], tpl["name"], tpl["kind"], tpl["title"], tpl["subtitle"], tpl["number_prefix"], tpl["default_currency"], tpl["vat_percent"], tpl["show_amount_in_words"], tpl["notes"], tpl["show_company_logo"], tpl["show_address"], tpl["logo_left"], tpl["logo_right"], tpl["watermark_on"], tpl["watermark_text"], tpl["signatures_json"], tpl["item_columns_json"], tpl["top_fields_json"], "active", tpl["id"]))
    # next_number for the copy starts at 1 (the INSERT above does not set it, default is 1)
    log(db, "invoice_template_use", tpl["name"]); db.commit(); flash("Template copied to your department. You can now use it and edit your own copy.", "ok")
    return redirect(url_for("invoices.templates"))

# ---------------------------------------------------------------- dept data sharing
@bp.route("/invoices/share-department", methods=["GET", "POST"])
@login_required
def share_department():
    _dept_admin_required()
    db = get_db()
    depts = db.execute("SELECT * FROM departments WHERE id != ? ORDER BY name", (g.user["department_id"],)).fetchall()
    if request.method == "POST":
        to_dept = int(request.form.get("to_department") or 0)
        scope = request.form.get("scope") or "invoices"
        if not to_dept:
            flash("Choose another department.", "error")
        else:
            db.execute("INSERT INTO invoice_dept_shares(from_department_id,to_department_id,shared_by,scope,expires) VALUES (?,?,?,?,?)",
                       (g.user["department_id"], to_dept, g.user["id"], scope, request.form.get("expires") or None))
            log(db, "invoice_dept_share", f"dept {to_dept} scope {scope}"); db.commit(); flash("Department invoices shared, view-only. The other dept admin cannot edit, void or mark paid your invoices.", "ok")
            return redirect(url_for("invoices.share_department"))
    shares = db.execute("SELECT s.*, d.name AS to_dept FROM invoice_dept_shares s JOIN departments d ON d.id=s.to_department_id WHERE s.from_department_id=? ORDER BY s.id DESC", (g.user["department_id"],)).fetchall()
    return render_template("invoice_share_department.html", depts=depts, shares=shares)

@bp.route("/invoices/share-department/<int:sid>/revoke", methods=["POST"])
@login_required
def share_department_revoke(sid):
    _dept_admin_required()
    db = get_db(); db.execute("UPDATE invoice_dept_shares SET revoked=1 WHERE id=? AND from_department_id=?", (sid, g.user["department_id"])); db.commit()
    flash("Share revoked.", "ok"); return redirect(url_for("invoices.share_department"))

# ---------------------------------------------------------------- create / edit invoice
@bp.route("/invoices/new", methods=["GET", "POST"])
@login_required
def invoice_new():
    db = get_db()
    template_id = request.values.get("template", type=int)
    tpl = _template(db, template_id) if template_id else None
    if tpl is not None and (tpl["department_id"] != g.user["department_id"] or tpl["status"] != "active"):
        flash("That template is not available to you.", "error"); return redirect(url_for("invoices.list_invoices"))
    if request.method == "POST" and tpl is not None:
        cur = request.form.get("currency") or tpl["default_currency"]
        if cur not in CURRENCIES:
            cur = tpl["default_currency"]
        lines = _parse_lines(request.form, tpl["kind"])
        if not lines:
            flash("Add at least one line.", "error")
        else:
            sub, vat, total = _totals(lines, tpl["vat_percent"])
            words = amount_in_words(total, cur) if tpl["show_amount_in_words"] else ""
            sigs = _sigs(request.form, tpl)
            iid = db.execute("INSERT INTO invoices(department_id,owner_id,template_id,title,subtitle,currency,customer_name,customer_address,reference,invoice_date,status,subtotal,vat_amount,total,amount_in_words,notes,signatures_json,template_snapshot_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (g.user["department_id"], g.user["id"], tpl["id"], tpl["title"], tpl["subtitle"], cur,
                              (request.form.get("customer_name") or "").strip(), request.form.get("customer_address") or "", (request.form.get("reference") or "").strip(),
                              request.form.get("invoice_date") or date.today().isoformat(), "draft", float(sub), float(vat), float(total), words,
                              request.form.get("notes") or tpl["notes"], json.dumps(sigs),
                              json.dumps({"name": tpl["name"], "kind": tpl["kind"], "title": tpl["title"], "subtitle": tpl["subtitle"], "vat_percent": tpl["vat_percent"], "logo_left": tpl["logo_left"], "logo_right": tpl["logo_right"], "watermark_on": tpl["watermark_on"], "watermark_text": tpl["watermark_text"]}))).lastrowid
            for i, l in enumerate(lines):
                db.execute("INSERT INTO invoice_lines(invoice_id,position,description,qty,rate,amount,line_date,from_place,to_place,mode,purpose,spec) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (iid, i, l["description"], float(l["qty"]), float(l["rate"]), float(l["amount"]), l["line_date"], l["from_place"], l["to_place"], l["mode"], l["purpose"], l["spec"]))
            log(db, "invoice_draft", f"template {tpl['name']}"); db.commit()
            flash("Draft saved. Finalize it to give it a number.", "ok")
            return redirect(url_for("invoices.detail", iid=iid))
    return render_template("invoice_form.html", tpl=tpl, inv=None, lines=[], sigs=json.loads(tpl["signatures_json"] or "[]") if tpl else [], currencies=CURRENCIES)

@bp.route("/invoices/<int:iid>/edit", methods=["GET", "POST"])
@login_required
def invoice_edit(iid):
    db = get_db(); inv = _invoice(db, iid)
    if inv["owner_id"] != g.user["id"] or inv["status"] != "draft":
        abort(403)
    tpl = _template(db, inv["template_id"]) if inv["template_id"] else None
    lines = _lines(db, iid)
    if request.method == "POST" and tpl is not None:
        cur = request.form.get("currency") or inv["currency"]
        if cur not in CURRENCIES:
            cur = inv["currency"]
        new_lines = _parse_lines(request.form, tpl["kind"])
        sub, vat, total = _totals(new_lines, tpl["vat_percent"])
        words = amount_in_words(total, cur) if tpl["show_amount_in_words"] else ""
        db.execute("UPDATE invoices SET currency=?,customer_name=?,customer_address=?,reference=?,invoice_date=?,subtotal=?,vat_amount=?,total=?,amount_in_words=?,notes=?,signatures_json=?,updated_at=datetime('now','localtime') WHERE id=?",
                   (cur, (request.form.get("customer_name") or "").strip(), request.form.get("customer_address") or "", (request.form.get("reference") or "").strip(),
                    request.form.get("invoice_date") or inv["invoice_date"], float(sub), float(vat), float(total), words, request.form.get("notes") or inv["notes"], json.dumps(_sigs(request.form, tpl)), iid))
        db.execute("DELETE FROM invoice_lines WHERE invoice_id=?", (iid,))
        for i, l in enumerate(new_lines):
            db.execute("INSERT INTO invoice_lines(invoice_id,position,description,qty,rate,amount,line_date,from_place,to_place,mode,purpose,spec) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (iid, i, l["description"], float(l["qty"]), float(l["rate"]), float(l["amount"]), l["line_date"], l["from_place"], l["to_place"], l["mode"], l["purpose"], l["spec"]))
        db.commit(); flash("Draft saved.", "ok"); return redirect(url_for("invoices.detail", iid=iid))
    return render_template("invoice_form.html", tpl=tpl, inv=inv, lines=lines, sigs=json.loads(inv["signatures_json"] or "[]") if inv["signatures_json"] else (json.loads(tpl["signatures_json"] or "[]") if tpl else []), currencies=CURRENCIES)

@bp.route("/invoices/<int:iid>/finalize", methods=["POST"])
@login_required
def invoice_finalize(iid):
    db = get_db(); inv = _invoice(db, iid)
    if inv["owner_id"] != g.user["id"] or inv["status"] != "draft":
        abort(403)
    tpl = _template(db, inv["template_id"])
    number = f"{tpl['number_prefix']}-{tpl['next_number']:04d}"
    db.execute("UPDATE invoice_templates SET next_number=next_number+1 WHERE id=?", (tpl["id"],))
    db.execute("UPDATE invoices SET number=?,status='issued',updated_at=datetime('now','localtime') WHERE id=?", (number, iid))
    log(db, "invoice_issued", number); db.commit(); flash(f"Invoice finalized and numbered {number}. It is now locked.", "ok")
    return redirect(url_for("invoices.detail", iid=iid))

@bp.route("/invoices/<int:iid>/mark-paid", methods=["POST"])
@login_required
def invoice_paid(iid):
    db = get_db(); inv = _invoice(db, iid)
    if not (inv["owner_id"] == g.user["id"] or (_is_dept_admin(g.user) and inv["department_id"] == g.user["department_id"])) or inv["status"] != "issued":
        abort(403)
    db.execute("UPDATE invoices SET status='paid' WHERE id=?", (iid,)); log(db, "invoice_paid", inv["number"] or str(iid)); db.commit()
    flash("Marked Paid.", "ok"); return redirect(url_for("invoices.detail", iid=iid))

@bp.route("/invoices/<int:iid>/void", methods=["POST"])
@login_required
def invoice_void(iid):
    db = get_db(); inv = _invoice(db, iid)
    if not (inv["owner_id"] == g.user["id"] or (_is_dept_admin(g.user) and inv["department_id"] == g.user["department_id"])) or inv["status"] not in ("issued", "paid"):
        abort(403)
    reason = (request.form.get("reason") or "").strip()
    db.execute("UPDATE invoices SET status='void',void_reason=?,public_enabled=0 WHERE id=?", (reason, iid)); log(db, "invoice_void", f"{inv['number']} {reason}"); db.commit()
    flash("Invoice voided. Its number is kept and never reused.", "ok"); return redirect(url_for("invoices.detail", iid=iid))

# ---------------------------------------------------------------- detail, PDF, public QR
@bp.route("/invoices/<int:iid>")
@login_required
def detail(iid):
    db = get_db(); inv = _invoice(db, iid)
    if not _can_view(db, g.user, inv):
        abort(403)
    lines = _lines(db, iid)
    tpl = _template(db, inv["template_id"]) if inv["template_id"] else None
    owner = db.execute("SELECT full_name FROM users WHERE id=?", (inv["owner_id"],)).fetchone()
    qr_svg = qr_url = None
    if inv["public_code"] and inv["public_enabled"]:
        qr_url = url_for("invoices.code_page", code=inv["public_code"], _external=True)
        qr_svg = _qr_svg(qr_url)
    return render_template("invoice_detail.html", inv=inv, lines=lines, tpl=tpl, owner_name=owner["full_name"] if owner else "",
                           qr_svg=qr_svg, qr_url=qr_url, colour=KIND_COLOURS.get((json.loads(inv["template_snapshot_json"] or "{}").get("kind") or "billing"), "#0F7CA6"),
                           can_edit=(inv["owner_id"] == g.user["id"] and inv["status"] == "draft"),
                           can_manage=(g.user["role"] == "admin" or inv["owner_id"] == g.user["id"] or (_is_dept_admin(g.user) and inv["department_id"] == g.user["department_id"])))

@bp.route("/invoices/<int:iid>/pdf")
@login_required
def invoice_pdf(iid):
    db = get_db(); inv = _invoice(db, iid)
    if not _can_view(db, g.user, inv):
        abort(403)
    data = _build_pdf(db, inv, show_amounts=True, show_customer=True, show_lines=True)
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{(inv["number"] or "invoice")}.pdf"'
    return resp

@bp.route("/invoices/<int:iid>/public", methods=["POST"])
@login_required
def invoice_public(iid):
    db = get_db(); inv = _invoice(db, iid)
    if not _can_manage_public(db, g.user, inv):
        abort(403)
    action = request.form.get("action", "save")
    if action == "off":
        db.execute("UPDATE invoices SET public_enabled=0 WHERE id=?", (iid,))
    elif action == "regenerate":
        # new code kills the old printed QR
        db.execute("UPDATE invoices SET public_code=?,public_enabled=1 WHERE id=?", (_new_invoice_code(db), iid))
    else:
        if inv["status"] not in ("issued", "paid"):
            flash("Only an Issued or Paid invoice can get a public QR. Draft and Void invoices do not get a live QR.", "error")
            return redirect(url_for("invoices.detail", iid=iid))
        code = inv["public_code"] or _new_invoice_code(db)
        db.execute("UPDATE invoices SET public_code=?,public_enabled=1,public_show_amounts=?,public_show_customer=?,public_show_lines=?,public_expires=? WHERE id=?",
                   (code, 1 if request.form.get("show_amounts") else 0, 1 if request.form.get("show_customer") else 0, 1 if request.form.get("show_lines") else 0,
                    request.form.get("public_expires") or None, iid))
    db.commit(); flash("Public QR saved.", "ok"); return redirect(url_for("invoices.detail", iid=iid))

@bp.route("/invoices/<int:iid>/qr")
@login_required
def invoice_qr(iid):
    db = get_db(); inv = _invoice(db, iid)
    if not _can_view(db, g.user, inv) or not inv["public_code"]:
        abort(404)
    url = url_for("invoices.code_page", code=inv["public_code"], _external=True)
    item = {"id": inv["id"], "title": inv["title"] or "Invoice", "dept": inv["number"] or "", "svg": _qr_svg(url), "url": url, "code": inv["public_code"]}
    return render_template("qr_label.html", items=[item], many=False)

def _public_check(db, inv):
    if inv is None or not inv["public_enabled"] or inv["status"] not in ("issued", "paid"):
        return False
    if inv["public_expires"] and inv["public_expires"] < date.today().isoformat():
        return False
    return True

@bp.route("/invoices/code/<code>")
@login_required
def code_page(code):
    """Login-only code view: a logged-in user types HRC-#####, sees the allowed fields, downloads the PDF."""
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if inv is None:
        return render_template("invoice_code.html", code=code, status="missing", inv=None, lines=[]), 404
    if not _public_check(db, inv):
        return render_template("invoice_code.html", code=code, status="off", inv=inv, lines=[]), 410
    db.execute("UPDATE invoices SET public_views=public_views+1 WHERE id=?", (inv["id"],)); db.commit()
    return render_template("invoice_code.html", code=code, status="ok", inv=inv, lines=_lines(db, inv["id"]))

@bp.route("/invoices/code/<code>/pdf")
@login_required
def code_pdf(code):
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if inv is None or not _public_check(db, inv):
        abort(404)
    data = _build_pdf(db, inv, show_amounts=bool(inv["public_show_amounts"]), show_customer=bool(inv["public_show_customer"]), show_lines=bool(inv["public_show_lines"]))
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{code}.pdf"'
    return resp

def _build_pdf(db, inv, show_amounts=True, show_customer=True, show_lines=True):
    lines = _lines(db, inv["id"])
    try:
        snap = json.loads(inv["template_snapshot_json"] or "{}")
    except Exception:
        snap = {}
    kind = snap.get("kind") or "billing"
    colour = KIND_COLOURS.get(kind, "#0F7CA6")
    company = setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME)
    # meta
    meta = []
    if inv["number"]:
        meta.append(("INVOICE NO.", inv["number"]))
    if inv["invoice_date"]:
        meta.append(("DATE", inv["invoice_date"]))
    if inv["reference"]:
        meta.append(("REFERENCE", inv["reference"]))
    bill_to = (inv["customer_name"] if show_customer else "—", inv["customer_address"] if show_customer else "")
    return exports.invoice_pdf(
        title=inv["title"] or KIND_TITLES.get(kind, "INVOICE"), subtitle=inv["subtitle"] or "",
        meta=meta, bill_to=bill_to, kind=kind, colour=colour,
        cols=_pdf_cols(kind), rows=_pdf_rows(lines, kind, inv["currency"], show_amounts, show_lines),
        totals=_pdf_totals(inv, show_amounts), words=(inv["amount_in_words"] if show_amounts else ""),
        terms=inv["notes"] or "", sigs=_pdf_sigs(inv), code=inv["public_code"] or "",
        company=company, logo_left=_logo_path(snap.get("logo_left")), logo_right=_logo_path(snap.get("logo_right")),
        watermark_on=bool(snap.get("watermark_on")), watermark_text=snap.get("watermark_text") or "")

def _pdf_cols(kind):
    if kind == "conveyance":
        return ["Date", "From", "To", "Mode", "Purpose", "Amount"]
    if kind == "admin":
        return ["#", "Item", "Purpose", "Amount"]
    if kind == "custom":
        return ["#", "Item", "Spec", "Qty", "Est. cost"]
    return ["#", "Description", "Qty", "Rate", "Amount"]

def _pdf_rows(lines, kind, cur, show_amounts, show_lines):
    if not show_lines:
        return [["", "Item lines hidden by the owner", "", "", "", ""][:len(_pdf_cols(kind))]]
    out = []
    for i, l in enumerate(lines, start=1):
        amt = _fmt(l["amount"], cur) if show_amounts else "—"
        if kind == "conveyance":
            out.append([l["line_date"] or "", l["from_place"] or "", l["to_place"] or "", l["mode"] or "", l["purpose"] or "", amt])
        elif kind == "admin":
            out.append([str(i), l["description"] or "", l["purpose"] or "", amt])
        elif kind == "custom":
            out.append([str(i), l["description"] or "", l["spec"] or "", str(l["qty"]), amt])
        else:
            out.append([str(i), l["description"] or "", str(l["qty"]), _fmt(l["rate"], cur) if show_amounts else "—", amt])
    return out

def _pdf_totals(inv, show_amounts):
    cur = inv["currency"]
    if not show_amounts:
        return [("Grand total", "—")]
    out = []
    if inv["subtotal"]:
        out.append(("Subtotal", _fmt(inv["subtotal"], cur)))
    if inv["vat_amount"]:
        out.append(("VAT", _fmt(inv["vat_amount"], cur)))
    out.append(("Grand total", _fmt(inv["total"], cur)))
    return out

def _pdf_sigs(inv):
    try:
        sigs = json.loads(inv["signatures_json"] or "[]")
    except Exception:
        sigs = []
    out = []
    owner = get_db().execute("SELECT full_name FROM users WHERE id=?", (inv["owner_id"],)).fetchone()
    out.append(("", owner["full_name"] if owner else "", "Prepared by"))
    for s in sigs[:2]:
        out.append(("", s.get("person") or "", f"{s.get('title') or 'Authorized'} · {s.get('designation') or ''}".strip(" ·")))
    return out[:3]
