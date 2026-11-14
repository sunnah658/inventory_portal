"""
routes_invoices.py - Invoices (NEW in this version, section 20 in README).

Dept admin creates invoice templates for their OWN department (not the portal admin).
Employees choose a template in the Invoices tab, fill it, save as Draft, then
Finalize and number it. Finalized invoices are locked: they can be marked
Approved (grey APPROVED seal on the PDF) or Pending (grey PENDING stamp),
or Deleted (only the owner or a portal admin, after typing their own
password), never quietly edited.

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
from utils import is_portal_admin
from core import display_code, external_url, new_random_code_text, notify, notify_admin_task, notify_ddb_row_task, notify_ddb_task, notify_dept_task
from models import get_db, log, setting_get

bp = Blueprint("invoices", __name__)
CURRENCIES = ["BDT", "USD", "EUR", "GBP", "INR"]
KIND_COLOURS = {"billing": "#0F7CA6", "admin": "#7C5CBF", "conveyance": "#1E8A5A", "custom": "#D97A1A"}
KIND_TITLES = {"billing": "INVOICE", "admin": "EXPENSE VOUCHER", "conveyance": "CONVEYANCE BILL", "custom": "PURCHASE REQUEST"}
STARTERS = [
    {"name": "Billing Invoice", "kind": "billing", "title": "INVOICE", "subtitle": "Original for customer", "prefix": "BIL", "vat": 5,
     "show_tax": 1,
     "notes": "Payment within 15 days. Bank: City Bank, A/C 1234567890.",
     "cols": "Description · Qty · Rate · Amount", "top": "Invoice date, Bill to (customer name), Customer address, Reference / PO number, Department"},
    {"name": "Admin Expense Voucher", "kind": "admin", "title": "EXPENSE VOUCHER", "subtitle": "Office expense voucher", "prefix": "ADM", "vat": 0,
     "show_tax": 0,
     "notes": "Bills attached. Reimbursement within 7 working days.",
     "cols": "Item · Purpose · Amount", "top": "Invoice date, Employee, Department, Purpose"},
    {"name": "Conveyance Bill", "kind": "conveyance", "title": "CONVEYANCE BILL", "subtitle": "Employee travel claim", "prefix": "CNV", "vat": 0,
     "show_tax": 0,
     "notes": "Attach rickshaw / CNG slips where available.",
     "cols": "Date · From · To · Mode · Purpose · Amount", "top": "Employee, Employee ID, Department, Period"},
    {"name": "Purchase Request", "kind": "custom", "title": "PURCHASE REQUEST", "subtitle": "Custom format", "prefix": "PRQ", "vat": 0,
     "show_tax": 0,
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
    return f"{_words(whole)} {word} Only"

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
    # A deleted invoice is gone from everywhere except the Recycle Bin
    # (build 60): the list, the detail page, the PDF and the QR code page
    # all act as if it does not exist.
    if row is None or row["deleted_at"]:
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
    if is_portal_admin(user):
        return True
    if inv["owner_id"] == user["id"]:
        return True
    # Department Database Invoices tab: every user in the same department can
    # SEE every invoice in that department (view only — editing, Approve /
    # Pending / Void and public-QR management keep their old owner /
    # dept-admin rules).
    if user["department_id"] == inv["department_id"]:
        return True
    if _is_dept_admin(user) and inv["department_id"] == user["department_id"]:
        return True
    if _is_dept_admin(user) and inv["department_id"] in _shared_dept_ids(db, user):
        return True
    # Anyone picked as a step on this invoice can open it and its PDF —
    # whatever department they are in — so an approver from another
    # department is never met with a 403. They can only approve or
    # reject when their turn comes; _can_act_invoice is unchanged.
    if db.execute("SELECT 1 FROM invoice_steps WHERE invoice_id=? AND user_id=?",
                  (inv["id"], user["id"])).fetchone():
        return True
    return False

def _can_manage_public(db, user, inv):
    return is_portal_admin(user) or inv["owner_id"] == user["id"] or (_is_dept_admin(user) and inv["department_id"] == user["department_id"])

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
                if db.execute("SELECT 1 FROM item_requests WHERE public_code=?", (cand,)).fetchone() is None:
                    if db.execute("SELECT 1 FROM applications WHERE public_code=?", (cand,)).fetchone() is None:
                        if db.execute("SELECT 1 FROM ddb_rows WHERE public_code=?", (cand,)).fetchone() is None:
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
    if is_portal_admin(g.user):
        args["dept"] = g.user["department_id"]
    return redirect(url_for("ddb.index", **args))
@bp.route("/invoices/dept")
@login_required
def dept_list():
    if not (_is_dept_admin(g.user) or is_portal_admin(g.user)):
        abort(403)
    db = get_db()
    dept_id = g.user["department_id"] if not is_portal_admin(g.user) else (request.args.get("dept", type=int) or g.user["department_id"])
    rows = db.execute("SELECT i.*, t.name AS template_name, u.full_name AS owner_name, u.is_active AS owner_is_active, u.is_deleted AS owner_is_deleted FROM invoices i "
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
        rows = db.execute(f"SELECT i.*, t.name AS template_name, u.full_name AS owner_name, u.is_active AS owner_is_active, u.is_deleted AS owner_is_deleted, d.name AS dept_name FROM invoices i "
                          f"LEFT JOIN invoice_templates t ON t.id=i.template_id LEFT JOIN users u ON u.id=i.owner_id LEFT JOIN departments d ON d.id=i.department_id "
                          f"WHERE i.department_id IN ({q}) ORDER BY i.id DESC", ids).fetchall()
    return render_template("invoice_shared_list.html", rows=rows)

# ---------------------------------------------------------------- templates
@bp.route("/invoices/templates")
@login_required
def templates():
    # A department admin sees their own department's templates; the
    # portal admin and administrative permission users see any
    # department's (with a department switcher) so they can delete a
    # template from any department.
    if not (_is_dept_admin(g.user) or is_portal_admin(g.user)):
        abort(403)
    db = get_db()
    if is_portal_admin(g.user):
        dept_id = request.args.get("dept", type=int) or g.user["department_id"] or db.execute("SELECT id FROM departments ORDER BY id LIMIT 1").fetchone()["id"]
        depts = db.execute("SELECT id, name FROM departments ORDER BY id").fetchall()
    else:
        dept_id = g.user["department_id"]
        depts = []
    rows = db.execute("SELECT * FROM invoice_templates WHERE department_id=? AND status != 'deleted' ORDER BY id", (dept_id,)).fetchall()
    # The list shows how many signature blocks the template still carries.
    # (The template used to render len() of the raw JSON text, which counted
    # characters — '[]' showed as 2. Old templates keep their stored blocks;
    # new ones carry none.)
    rows = [dict(r, sig_count=len(json.loads(r["signatures_json"] or "[]"))) for r in rows]
    shared = db.execute("SELECT s.*, t.name AS template_name, t.kind AS kind, d.name AS from_dept FROM invoice_template_shares s "
                        "JOIN invoice_templates t ON t.id=s.template_id JOIN departments d ON d.id=s.from_department_id "
                        "WHERE s.to_department_id=? AND s.revoked=0 AND (s.expires IS NULL OR s.expires='' OR s.expires >= date('now','localtime')) ORDER BY s.id DESC",
                        (dept_id,)).fetchall()
    return render_template("invoice_templates.html", rows=rows, shared=shared, colours=KIND_COLOURS,
                           depts=depts, dept_id=dept_id,
                           can_manage_templates=(_is_dept_admin(g.user) and g.user["department_id"] == dept_id))

@bp.route("/invoices/templates/delete", methods=["POST"])
@login_required
def templates_delete():
    """Delete the selected invoice templates. A department admin deletes
    only their own department's templates; the portal admin and
    administrative permission users delete any department's. A deleted
    template disappears from the list and the picker at once and does not
    go to the Recycle Bin — but the invoices already made from it stay
    exactly as they are: their frozen copy keeps working, and the
    template row is kept behind the scenes for them."""
    db = get_db()
    ids = [int(x) for x in request.form.getlist("template_ids") if str(x).isdigit()]
    if not ids:
        flash("Select at least one template to delete.", "error")
        return redirect(url_for("invoices.templates"))
    rows = db.execute("SELECT * FROM invoice_templates WHERE id IN (%s)" % ",".join("?" * len(ids)), tuple(ids)).fetchall()
    if not rows:
        flash("Those templates were not found.", "error")
        return redirect(url_for("invoices.templates"))
    for t in rows:
        if not (is_portal_admin(g.user) or (_is_dept_admin(g.user) and t["department_id"] == g.user["department_id"])):
            abort(403)
    db.execute("UPDATE invoice_templates SET status='deleted' WHERE id IN (%s)" % ",".join("?" * len(ids)), tuple(ids))
    log(db, "invoice_template_deleted", f"{len(rows)} template(s)")
    db.commit()
    flash(f"Deleted {len(rows)} template{'s' if len(rows) != 1 else ''}. The invoices made from them stay as they are.", "ok")
    if is_portal_admin(g.user):
        return redirect(url_for("invoices.templates", dept=rows[0]["department_id"]))
    return redirect(url_for("invoices.templates"))

@bp.route("/invoices/templates/starters", methods=["POST"])
@login_required
def starters():
    _dept_admin_required()
    db = get_db()
    for s in STARTERS:
        if db.execute("SELECT 1 FROM invoice_templates WHERE department_id=? AND name=? AND status != 'deleted'", (g.user["department_id"], s["name"])).fetchone():
            continue
        db.execute("INSERT INTO invoice_templates(department_id,created_by,name,kind,title,subtitle,number_prefix,default_currency,vat_percent,show_tax,notes,item_columns_json,top_fields_json,signatures_json,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (g.user["department_id"], g.user["id"], s["name"], s["kind"], s["title"], s["subtitle"], s["prefix"], "BDT", s["vat"], s["show_tax"], s["notes"], s["cols"], s["top"], json.dumps([{"title": "Authorized by", "person": "", "designation": ""}, {"title": "Approved by", "person": "", "designation": ""}]), "active"))
    log(db, "invoice_starters", f"dept {g.user['department_id']}")
    notify_dept_task(db, g.user,
                     f"{g.user['full_name']} created the starter invoice templates.",
                     url_for("invoices.templates"))
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
            flash("Write a template name.", "error"); return render_template("invoice_template_form.html", tpl=None, currencies=CURRENCIES, default_company_name=setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME), default_company_address=config.DEFAULT_COMPANY_ADDRESS)
        left = _save_logo(request.files.get("logo_left")); right = _save_logo(request.files.get("logo_right"))
        sigs = _sigs(request.form)
        tid = db.execute("INSERT INTO invoice_templates(department_id,created_by,name,kind,title,subtitle,number_prefix,default_currency,vat_percent,show_tax,show_amount_in_words,notes,show_company_logo,show_address,company_name,company_address,logo_left,logo_right,watermark_on,watermark_text,signatures_json,item_columns_json,top_fields_json,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (g.user["department_id"], g.user["id"], name, request.form.get("kind") or "billing", (request.form.get("title") or "INVOICE").strip(), (request.form.get("subtitle") or "").strip(),
                          (request.form.get("number_prefix") or "BIL").strip().upper()[:10], request.form.get("currency") or "BDT", float(request.form.get("vat") or 0),
                          1 if request.form.get("show_tax") else 0,
                          1 if request.form.get("amount_in_words") else 0, request.form.get("notes") or "",
                          1 if request.form.get("show_company_logo") else 0, 1 if request.form.get("show_address") else 0,
                          (request.form.get("company_name") or "").strip(), (request.form.get("company_address") or "").strip(), left, right,
                          1 if request.form.get("watermark_on") else 0, (request.form.get("watermark_text") or "").strip()[:50],
                          json.dumps(sigs), request.form.get("item_columns") or "", request.form.get("top_fields") or "", "active" if request.form.get("status") != "draft" else "draft")).lastrowid
        log(db, "invoice_template_new", name)
        notify_dept_task(db, g.user,
                         f"{g.user['full_name']} created the invoice template '{name}'.",
                         url_for("invoices.templates"))
        db.commit(); flash("Template saved.", "ok")
        return redirect(url_for("invoices.templates"))
    return render_template("invoice_template_form.html", tpl=None, sigs=[], currencies=CURRENCIES, default_company_name=setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME), default_company_address=config.DEFAULT_COMPANY_ADDRESS)

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
        db.execute("UPDATE invoice_templates SET name=?,kind=?,title=?,subtitle=?,number_prefix=?,default_currency=?,vat_percent=?,show_tax=?,show_amount_in_words=?,notes=?,show_company_logo=?,show_address=?,company_name=?,company_address=?,logo_left=?,logo_right=?,watermark_on=?,watermark_text=?,signatures_json=?,item_columns_json=?,top_fields_json=?,status=?,updated_at=datetime('now','localtime') WHERE id=?",
                   ((request.form.get("name") or tpl["name"]).strip(), request.form.get("kind") or tpl["kind"], (request.form.get("title") or "INVOICE").strip(), (request.form.get("subtitle") or "").strip(),
                    (request.form.get("number_prefix") or tpl["number_prefix"]).strip().upper()[:10], request.form.get("currency") or tpl["default_currency"], float(request.form.get("vat") or 0),
                    1 if request.form.get("show_tax") else 0,
                    1 if request.form.get("amount_in_words") else 0, request.form.get("notes") or "",
                    1 if request.form.get("show_company_logo") else 0, 1 if request.form.get("show_address") else 0,
                    (request.form.get("company_name") or "").strip(), (request.form.get("company_address") or "").strip(), left, right,
                    1 if request.form.get("watermark_on") else 0, (request.form.get("watermark_text") or "").strip()[:50],
                    json.dumps(_sigs(request.form, tpl)), request.form.get("item_columns") or "", request.form.get("top_fields") or "",
                    "active" if request.form.get("status") != "draft" else "draft", tid))
        log(db, "invoice_template_edit", tpl["name"])
        notify_dept_task(db, g.user,
                         f"{g.user['full_name']} edited the invoice template '{tpl['name']}'.",
                         url_for("invoices.templates"))
        db.commit(); flash("Template saved. Changes apply to new invoices only; issued invoices keep their old format.", "ok")
        return redirect(url_for("invoices.templates"))
    return render_template("invoice_template_form.html", tpl=tpl, sigs=json.loads(tpl["signatures_json"] or "[]") if tpl["signatures_json"] else [], currencies=CURRENCIES, default_company_name=setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME), default_company_address=config.DEFAULT_COMPANY_ADDRESS)

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
            to_name = db.execute("SELECT name FROM departments WHERE id=?", (to_dept,)).fetchone()["name"]
            log(db, "invoice_template_share", f"{tpl['name']} -> dept {to_dept}")
            notify_dept_task(db, g.user,
                             f"{g.user['full_name']} shared the invoice template '{tpl['name']}' with {to_name}.",
                             url_for("invoices.templates"))
            db.commit(); flash("Template shared. The other dept admin can now use it in their department.", "ok")
            return redirect(url_for("invoices.templates"))
    shares = db.execute("SELECT s.*, d.name AS to_dept FROM invoice_template_shares s JOIN departments d ON d.id=s.to_department_id WHERE s.template_id=? ORDER BY s.id DESC", (tid,)).fetchall()
    return render_template("invoice_template_share.html", tpl=tpl, depts=depts, shares=shares)

@bp.route("/invoices/templates/shares/<int:sid>/revoke", methods=["POST"])
@login_required
def template_share_revoke(sid):
    _dept_admin_required()
    db = get_db()
    share = db.execute("SELECT s.*, t.name AS tpl_name, d.name AS to_name FROM invoice_template_shares s "
                       "JOIN invoice_templates t ON t.id=s.template_id JOIN departments d ON d.id=s.to_department_id "
                       "WHERE s.id=? AND s.from_department_id=?", (sid, g.user["department_id"])).fetchone()
    db.execute("UPDATE invoice_template_shares SET revoked=1 WHERE id=? AND from_department_id=?", (sid, g.user["department_id"]))
    if share:
        log(db, "invoice_template_share_revoke", share["tpl_name"])
        notify_dept_task(db, g.user,
                         f"{g.user['full_name']} stopped sharing the invoice template '{share['tpl_name']}' with {share['to_name']}.",
                         url_for("invoices.templates"))
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
    db.execute("INSERT INTO invoice_templates(department_id,created_by,name,kind,title,subtitle,number_prefix,default_currency,vat_percent,show_tax,show_amount_in_words,notes,show_company_logo,show_address,company_name,company_address,logo_left,logo_right,watermark_on,watermark_text,signatures_json,item_columns_json,top_fields_json,status,shared_from_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (g.user["department_id"], g.user["id"], tpl["name"], tpl["kind"], tpl["title"], tpl["subtitle"], tpl["number_prefix"], tpl["default_currency"], tpl["vat_percent"], tpl["show_tax"], tpl["show_amount_in_words"], tpl["notes"], tpl["show_company_logo"], tpl["show_address"], tpl["company_name"], tpl["company_address"], tpl["logo_left"], tpl["logo_right"], tpl["watermark_on"], tpl["watermark_text"], tpl["signatures_json"], tpl["item_columns_json"], tpl["top_fields_json"], "active", tpl["id"]))
    # next_number for the copy starts at 1 (the INSERT above does not set it, default is 1)
    log(db, "invoice_template_use", tpl["name"])
    notify_dept_task(db, g.user,
                     f"{g.user['full_name']} copied the shared invoice template '{tpl['name']}' into their department.",
                     url_for("invoices.templates"))
    db.commit(); flash("Template copied to your department. You can now use it and edit your own copy.", "ok")
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
            to_name = db.execute("SELECT name FROM departments WHERE id=?", (to_dept,)).fetchone()["name"]
            log(db, "invoice_dept_share", f"dept {to_dept} scope {scope}")
            notify_dept_task(db, g.user,
                             f"{g.user['full_name']} shared the department's invoices with {to_name}.",
                             url_for("invoices.share_department"))
            db.commit(); flash("Department invoices shared, view-only. The other dept admin cannot edit, void or mark paid your invoices.", "ok")
            return redirect(url_for("invoices.share_department"))
    shares = db.execute("SELECT s.*, d.name AS to_dept FROM invoice_dept_shares s JOIN departments d ON d.id=s.to_department_id WHERE s.from_department_id=? ORDER BY s.id DESC", (g.user["department_id"],)).fetchall()
    return render_template("invoice_share_department.html", depts=depts, shares=shares)

@bp.route("/invoices/share-department/<int:sid>/revoke", methods=["POST"])
@login_required
def share_department_revoke(sid):
    _dept_admin_required()
    db = get_db()
    share = db.execute("SELECT s.*, d.name AS to_name FROM invoice_dept_shares s JOIN departments d ON d.id=s.to_department_id "
                       "WHERE s.id=? AND s.from_department_id=?", (sid, g.user["department_id"])).fetchone()
    db.execute("UPDATE invoice_dept_shares SET revoked=1 WHERE id=? AND from_department_id=?", (sid, g.user["department_id"]))
    if share:
        log(db, "invoice_dept_share_revoke", share["to_name"])
        notify_dept_task(db, g.user,
                         f"{g.user['full_name']} stopped sharing the department's invoices with {share['to_name']}.",
                         url_for("invoices.share_department"))
    db.commit()
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
        # Who approves it: up to 3 steps, picked here, exactly like an
        # application letter. The dept admin no longer sets signatures on
        # the template — the user picks the chain when the invoice is made.
        chain, chain_err = _parse_invoice_chain(request.form, _invoice_chain_people(db))
        if chain_err:
            flash(chain_err, "error")
            return render_template("invoice_form.html", tpl=tpl, inv=None, lines=[], currencies=CURRENCIES,
                                   chain_people=_invoice_chain_people(db), chain_depts=_invoice_chain_depts(db),
                                   steps=_chain_from_form(request.form))
        lines = _parse_lines(request.form, tpl["kind"])
        if not lines:
            flash("Add at least one line.", "error")
        else:
            # Tax tick: unticked template = no tax option at all for the user.
            sub, vat, total = _totals(lines, tpl["vat_percent"] if tpl["show_tax"] else 0)
            words = amount_in_words(total, cur) if tpl["show_amount_in_words"] else ""
            iid = db.execute("INSERT INTO invoices(department_id,owner_id,template_id,title,subtitle,currency,customer_name,customer_address,reference,invoice_date,status,subtotal,vat_amount,total,amount_in_words,notes,signatures_json,template_snapshot_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (g.user["department_id"], g.user["id"], tpl["id"], tpl["title"], tpl["subtitle"], cur,
                              (request.form.get("customer_name") or "").strip(), request.form.get("customer_address") or "", (request.form.get("reference") or "").strip(),
                              request.form.get("invoice_date") or date.today().isoformat(), "draft", float(sub), float(vat), float(total), words,
                              request.form.get("notes") or tpl["notes"], "[]",
                              json.dumps({"name": tpl["name"], "kind": tpl["kind"], "title": tpl["title"], "subtitle": tpl["subtitle"], "vat_percent": tpl["vat_percent"], "show_tax": tpl["show_tax"], "logo_left": tpl["logo_left"], "logo_right": tpl["logo_right"], "watermark_on": tpl["watermark_on"], "watermark_text": tpl["watermark_text"], "company_name": tpl["company_name"], "company_address": tpl["company_address"], "show_address": tpl["show_address"]}))).lastrowid
            _save_invoice_chain(db, iid, chain)
            for i, l in enumerate(lines):
                db.execute("INSERT INTO invoice_lines(invoice_id,position,description,qty,rate,amount,line_date,from_place,to_place,mode,purpose,spec) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (iid, i, l["description"], float(l["qty"]), float(l["rate"]), float(l["amount"]), l["line_date"], l["from_place"], l["to_place"], l["mode"], l["purpose"], l["spec"]))
            log(db, "invoice_draft", f"template {tpl['name']}")
            # The department admin is told a user in their department made
            # an invoice (a draft). The watcher router tells the dept admins
            # for a regular user, the portal admin for a dept-admin or
            # permission user, and nobody for a true portal admin.
            _dept = db.execute("SELECT * FROM departments WHERE id=?", (g.user["department_id"],)).fetchone()
            notify_ddb_task(db, g.user, _dept,
                            f"{g.user['full_name']} created an invoice draft ({tpl['title']}).",
                            url_for("invoices.detail", iid=iid))
            db.commit()
            flash("Draft saved. Finalize it to give it a number.", "ok")
            return redirect(url_for("invoices.detail", iid=iid))
    return render_template("invoice_form.html", tpl=tpl, inv=None, lines=[], currencies=CURRENCIES,
                           chain_people=_invoice_chain_people(db), chain_depts=_invoice_chain_depts(db), steps=[])

@bp.route("/invoices/<int:iid>/edit", methods=["GET", "POST"])
@login_required
def invoice_edit(iid):
    db = get_db(); inv = _invoice(db, iid)
    # The owner can edit a draft. Once it has a number it is locked. The
    # owner no longer sets Approved or Pending here — the chain decides
    # the status once the invoice is finalised.
    if inv["owner_id"] != g.user["id"] or inv["status"] != "draft" or inv["number"]:
        abort(403)
    tpl = _template(db, inv["template_id"]) if inv["template_id"] else None
    lines = _lines(db, iid)
    if request.method == "POST" and tpl is not None:
        cur = request.form.get("currency") or inv["currency"]
        if cur not in CURRENCIES:
            cur = inv["currency"]
        chain, chain_err = _parse_invoice_chain(request.form, _invoice_chain_people(db))
        if chain_err:
            flash(chain_err, "error")
            return render_template("invoice_form.html", tpl=tpl, inv=inv, lines=lines, currencies=CURRENCIES,
                                   chain_people=_invoice_chain_people(db), chain_depts=_invoice_chain_depts(db),
                                   steps=_chain_from_form(request.form))
        new_lines = _parse_lines(request.form, tpl["kind"])
        sub, vat, total = _totals(new_lines, tpl["vat_percent"] if tpl["show_tax"] else 0)
        words = amount_in_words(total, cur) if tpl["show_amount_in_words"] else ""
        db.execute("UPDATE invoices SET currency=?,customer_name=?,customer_address=?,reference=?,invoice_date=?,subtotal=?,vat_amount=?,total=?,amount_in_words=?,notes=?,updated_at=datetime('now','localtime') WHERE id=?",
                   (cur, (request.form.get("customer_name") or "").strip(), request.form.get("customer_address") or "", (request.form.get("reference") or "").strip(),
                    request.form.get("invoice_date") or inv["invoice_date"], float(sub), float(vat), float(total), words, request.form.get("notes") or inv["notes"], iid))
        _save_invoice_chain(db, iid, chain)
        db.execute("DELETE FROM invoice_lines WHERE invoice_id=?", (iid,))
        for i, l in enumerate(new_lines):
            db.execute("INSERT INTO invoice_lines(invoice_id,position,description,qty,rate,amount,line_date,from_place,to_place,mode,purpose,spec) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (iid, i, l["description"], float(l["qty"]), float(l["rate"]), float(l["amount"]), l["line_date"], l["from_place"], l["to_place"], l["mode"], l["purpose"], l["spec"]))
        db.commit(); flash("Draft saved.", "ok"); return redirect(url_for("invoices.detail", iid=iid))
    return render_template("invoice_form.html", tpl=tpl, inv=inv, lines=lines, currencies=CURRENCIES,
                           chain_people=_invoice_chain_people(db), chain_depts=_invoice_chain_depts(db),
                           steps=[{"role": s["role"], "user_id": s["user_id"]} for s in _invoice_steps(db, iid)])

@bp.route("/invoices/<int:iid>/finalize", methods=["POST"])
@login_required
def invoice_finalize(iid):
    db = get_db(); inv = _invoice(db, iid)
    if inv["owner_id"] != g.user["id"] or inv["status"] != "draft":
        abort(403)
    steps = _invoice_steps(db, iid)
    if not steps:
        # A draft made before the chain existed has nobody to forward to:
        # the owner picks the steps on the edit page first.
        flash("Choose who approves this invoice first — edit the draft and pick at least one step.", "error")
        return redirect(url_for("invoices.invoice_edit", iid=iid))
    tpl = _template(db, inv["template_id"])
    number = f"{tpl['number_prefix']}-{tpl['next_number']:04d}"
    db.execute("UPDATE invoice_templates SET next_number=next_number+1 WHERE id=?", (tpl["id"],))
    # Finalising gives the invoice its number and starts it forwarding:
    # the status becomes Pending and the first person in the chain is
    # told it is with them. The last step's approval makes it Approved;
    # a rejection at any step makes it Rejected.
    db.execute("UPDATE invoices SET number=?,status='pending',updated_at=datetime('now','localtime') WHERE id=?", (number, iid))
    log(db, "invoice_issued", number)
    first = steps[0]
    if first["user_id"]:
        notify(db, [first["user_id"]],
               f"{g.user['full_name']} sent you invoice {number} to {INVOICE_STEP_VERBS[first['role']]}.",
               url_for("invoices.detail", iid=iid), skip=g.user["id"])
    # The department admin is told a user in their department finalised
    # an invoice — except the first person in the chain, who was already
    # told directly above.
    _dept = db.execute("SELECT * FROM departments WHERE id=?", (inv["department_id"],)).fetchone()
    notify_ddb_task(db, g.user, _dept,
                    f"{g.user['full_name']} finalised invoice {number}.",
                    url_for("invoices.detail", iid=iid), skip=first["user_id"] if first["user_id"] else None)
    db.commit()
    flash(f"Invoice finalized and numbered {number}. It is now with {first['full_name'] or 'the first approver'}. It is now locked.", "ok")
    return redirect(url_for("invoices.detail", iid=iid))

@bp.route("/invoices/<int:iid>/step-signature", methods=["POST"])
@login_required
def invoice_step_signature(iid):
    return _sign_invoice_step(iid)

@bp.route("/invoices/<int:iid>/decide", methods=["POST"])
@login_required
def invoice_decide(iid):
    return _decide_invoice(iid)

@bp.route("/invoices/<int:iid>/void", methods=["POST"])
@login_required
def invoice_void(iid):
    db = get_db(); inv = _invoice(db, iid)
    if not (inv["owner_id"] == g.user["id"] or (_is_dept_admin(g.user) and inv["department_id"] == g.user["department_id"])) or inv["status"] not in ("issued", "paid", "approved", "pending"):
        abort(403)
    reason = (request.form.get("reason") or "").strip()
    db.execute("UPDATE invoices SET status='void',void_reason=?,public_enabled=0 WHERE id=?", (reason, iid))
    log(db, "invoice_void", f"{inv['number']} {reason}")
    if _is_dept_admin(g.user) and inv["department_id"] == g.user["department_id"]:
        notify_dept_task(db, g.user,
                         f"{g.user['full_name']} voided invoice {inv['number']}.",
                         url_for("invoices.detail", iid=iid))
    else:
        notify_ddb_row_task(db, g.user, inv["department_id"],
                            f"{g.user['full_name']} voided invoice {inv['number']}.",
                            url_for("invoices.detail", iid=iid))
    db.commit()
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
        qr_url = external_url(db, "invoices.code_page", code=inv["public_code"])
        qr_svg = _qr_svg(qr_url)
    steps = _invoice_steps(db, iid)
    return render_template("invoice_detail.html", inv=inv, lines=lines, tpl=tpl, owner_name=owner["full_name"] if owner else "",
                           qr_svg=qr_svg, qr_url=qr_url, colour=KIND_COLOURS.get((json.loads(inv["template_snapshot_json"] or "{}").get("kind") or "billing"), "#0F7CA6"),
                           steps=steps, step_roles=INVOICE_STEP_ROLES, current_step=_current_invoice_step(db, iid),
                           can_act=_can_act_invoice(db, g.user, inv),
                           can_finalize=(inv["owner_id"] == g.user["id"] and inv["status"] == "draft" and not inv["number"]),
                           can_edit=(inv["owner_id"] == g.user["id"] and inv["status"] == "draft" and not inv["number"]),
                           can_delete=(is_portal_admin(g.user) or inv["owner_id"] == g.user["id"]),
                           can_manage=(is_portal_admin(g.user) or inv["owner_id"] == g.user["id"] or (_is_dept_admin(g.user) and inv["department_id"] == g.user["department_id"])))

@bp.route("/invoices/<int:iid>/delete", methods=["POST"])
@login_required
def invoice_delete(iid):
    """Move an invoice to the Recycle Bin (build 60: it used to be deleted
    for good). Only the owner or a portal admin may do it, and only after
    typing their own password in the warning pop-up. The invoice, its lines
    and its chain stay in the bin for 30 days and can be restored; its
    number is never reused. If the owner deletes it, the department admin
    is told."""
    from security import reauth_ok
    db = get_db(); inv = _invoice(db, iid)
    if not (inv["owner_id"] == g.user["id"] or is_portal_admin(g.user)):
        abort(403)
    if not reauth_ok(g.user, request.form):
        flash("Wrong password. The invoice was not deleted.", "err")
        return redirect(url_for("invoices.detail", iid=iid))
    number = inv["number"] or "draft"
    dept_id = inv["department_id"]
    db.execute("UPDATE invoices SET deleted_at=datetime('now','localtime'), deleted_by=? WHERE id=?",
               (g.user["id"], iid))
    log(db, "invoice_deleted", number)
    # If the owner deletes it, the department admin is told. A portal
    # admin deleting it tells nobody (the watcher rule: nobody is told
    # about a portal admin's own actions).
    if inv["owner_id"] == g.user["id"] and not is_portal_admin(g.user):
        notify_ddb_row_task(db, g.user, dept_id,
                            f"{g.user['full_name']} deleted invoice {number}.",
                            url_for("ddb.index", dept=dept_id, tab="invoices"))
    db.commit()
    flash(f"Invoice {number} moved to the Recycle Bin.", "ok")
    return redirect(url_for("ddb.index", dept=dept_id, tab="invoices"))


@bp.route("/invoices/<int:iid>/pdf")
@login_required
def invoice_pdf(iid):
    db = get_db(); inv = _invoice(db, iid)
    if not _can_view(db, g.user, inv):
        abort(403)
    # ?watermark=0 downloads the PDF without any watermark (no seal, no
    # stamp, no diagonal template watermark); the default shows it.
    data = _build_pdf(db, inv, show_amounts=True, show_customer=True, show_lines=True,
                      hide_watermark=(request.args.get("watermark") == "0"))
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
        if inv["status"] not in ("issued", "paid", "approved", "pending"):
            flash("Only an Issued, Approved, Pending or Paid invoice can get a public QR. Draft and Void invoices do not get a live QR.", "error")
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
    url = external_url(db, "invoices.code_page", code=inv["public_code"])
    item = {"id": inv["id"], "title": inv["title"] or "Invoice", "dept": inv["number"] or "", "svg": _qr_svg(url), "url": url, "code": inv["public_code"]}
    return render_template("qr_label.html", items=[item], many=False)

def _public_check(db, inv):
    if inv is None or inv["deleted_at"] or not inv["public_enabled"] or inv["status"] not in ("issued", "paid", "approved", "pending"):
        return False
    if inv["public_expires"] and inv["public_expires"] < date.today().isoformat():
        return False
    return True

@bp.route("/invoices/code/<code>")
def code_page(code):
    """Public code view: anyone who scans the QR (or types HRC-#####) sees the allowed fields and downloads the PDF. No login needed."""
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if inv is None:
        return render_template("invoice_code.html", code=code, status="missing", inv=None, lines=[]), 404
    if not _public_check(db, inv):
        return render_template("invoice_code.html", code=code, status="off", inv=inv, lines=[]), 410
    db.execute("UPDATE invoices SET public_views=public_views+1 WHERE id=?", (inv["id"],)); db.commit()
    return render_template("invoice_code.html", code=code, status="ok", inv=inv, lines=_lines(db, inv["id"]))

@bp.route("/invoices/code/<code>/pdf")
def code_pdf(code):
    db = get_db()
    inv = db.execute("SELECT * FROM invoices WHERE public_code=?", (code.strip().upper(),)).fetchone()
    if inv is None or not _public_check(db, inv):
        abort(404)
    data = _build_pdf(db, inv, show_amounts=bool(inv["public_show_amounts"]), show_customer=bool(inv["public_show_customer"]), show_lines=bool(inv["public_show_lines"]))
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{code}.pdf"'
    return resp

def _build_pdf(db, inv, show_amounts=True, show_customer=True, show_lines=True, hide_watermark=False):
    lines = _lines(db, inv["id"])
    try:
        snap = json.loads(inv["template_snapshot_json"] or "{}")
    except Exception:
        snap = {}
    kind = snap.get("kind") or "billing"
    colour = KIND_COLOURS.get(kind, "#0F7CA6")
    company = snap.get("company_name") or setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME)
    # Per-template header: an invoice keeps the header it was made with (from
    # its snapshot). Older invoices have no header in their snapshot, so they
    # fall back to the portal name and the default address — the same look as
    # before, except the email no longer appears.
    address = snap.get("company_address") or config.DEFAULT_COMPANY_ADDRESS
    show_address = snap.get("show_address", 1)
    # meta
    meta = []
    if inv["number"]:
        meta.append(("INVOICE NO.", inv["number"]))
    if inv["invoice_date"]:
        meta.append(("DATE", inv["invoice_date"]))
    if inv["reference"]:
        meta.append(("REFERENCE", inv["reference"]))
    # "Bill to" is only for an invoice that has a customer: the
    # Conveyance form has no customer field, so its invoices must not
    # print an empty "Bill to -" line — and the public view must not
    # print "Bill to - —" either. A customer that exists but is hidden
    # still shows the "—".
    if (inv["customer_name"] or "").strip():
        bill_to = (inv["customer_name"] if show_customer else "—", inv["customer_address"] if show_customer else "")
    else:
        bill_to = ("", "")
    qr_url = external_url(db, "invoices.code_page", code=inv["public_code"]) if inv["public_code"] else ""
    return exports.invoice_pdf(
        title=inv["title"] or KIND_TITLES.get(kind, "INVOICE"), subtitle=inv["subtitle"] or "",
        meta=meta, bill_to=bill_to, kind=kind, colour=colour,
        cols=_pdf_cols(kind), rows=_pdf_rows(lines, kind, inv["currency"], show_amounts, show_lines),
        totals=_pdf_totals(inv, show_amounts), words=(inv["amount_in_words"] if show_amounts else ""),
        terms=inv["notes"] or "", sigs=_pdf_sigs(inv), code=inv["public_code"] or "",
        company=company, company_address=address, show_address=bool(show_address),
        logo_left=_logo_path(snap.get("logo_left")), logo_right=_logo_path(snap.get("logo_right")),
        watermark_on=bool(snap.get("watermark_on")), watermark_text=snap.get("watermark_text") or "",
        qr_url=qr_url, is_approved=(inv["status"] == "approved"), is_pending=(inv["status"] == "pending"),
        is_rejected=(inv["status"] == "rejected"), hide_watermark=hide_watermark)

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
    """Every signature on the invoice. A chained invoice (made after the
    approval chain) shows the owner's block (Prepared By) plus one block
    per chain step, each with the step's saved signature image, the role
    label ("Rejected By" when that step rejected), the name, the
    designation and the department — the same blocks as the application
    letter's FOR OFFICE USE. The owner's block shows the signature the
    owner saved in My settings, above the name, exactly like the steps
    show theirs; the PDF is built fresh on every download, so it reads
    the signature the owner has saved now — which is also what makes an
    invoice that was already issued show it. An older invoice keeps
    exactly what it had: the owner's block plus ALL of the template's
    signatures as text (title, person, designation), from its own frozen
    copy. An owner with no saved signature keeps the old text block
    with its line, on a chained invoice and on an older one."""
    steps = _invoice_steps(get_db(), inv["id"])
    owner = get_db().execute("SELECT full_name, designation, signature_path FROM users WHERE id=?", (inv["owner_id"],)).fetchone()
    owner_sig = None
    if owner and owner["signature_path"]:
        _p = os.path.join(config.UPLOAD_DIR, "user_signatures", os.path.basename(owner["signature_path"]))
        if os.path.exists(_p):
            owner_sig = _p
    if owner_sig:
        owner_block = ("Prepared By", owner["full_name"] if owner else "", owner["designation"] if owner else "", "", owner_sig)
    else:
        owner_block = ("Prepared By", owner["full_name"] if owner else "", owner["designation"] if owner else "")
    if steps:
        out = [owner_block]
        for s in steps:
            label = "Rejected By" if s["status"] == "rejected" else INVOICE_STEP_ROLES.get(s["role"], s["role"])
            img = os.path.join(config.UPLOAD_DIR, "inv_signatures", os.path.basename(s["signature_path"])) if s["signature_path"] else None
            out.append((label, s["full_name"] or "", s["designation"] or "", s["dept_name"] or "", img))
        return out
    try:
        sigs = json.loads(inv["signatures_json"] or "[]")
    except Exception:
        sigs = []
    out = []
    out.append(owner_block)
    for s in sigs:
        out.append((s.get("title") or "Authorized", s.get("person") or "", s.get("designation") or ""))
    return out

# ---------------------------------------------------------------- approval chain
# An invoice is approved the same way as an application letter: the owner
# picks up to 3 steps when the draft is made (role + a person from ANY
# department), Finalise gives the invoice its number and starts it
# forwarding through the steps in order, each person must tick "Use my
# signature" before approving or rejecting, and the invoice's status
# follows the chain — Pending while it forwards, Approved when the last
# person approves, Rejected as soon as anyone rejects.
INVOICE_STEP_ROLES = {"checked": "Checked By", "approved": "Approved By", "authorised": "Authorised By"}
INVOICE_STEP_VERBS = {"checked": "check", "approved": "approve", "authorised": "authorise"}

def _invoice_steps(db, iid):
    """The approval chain for an invoice, in order, with each step's user's name, designation and department. A step whose user was purged has user_id None and no name — it still shows, with a blank name."""
    return db.execute("SELECT s.*, u.full_name, u.designation, d.name AS dept_name FROM invoice_steps s "
                      "LEFT JOIN users u ON u.id=s.user_id LEFT JOIN departments d ON d.id=u.department_id "
                      "WHERE s.invoice_id=? ORDER BY s.position", (iid,)).fetchall()

def _current_invoice_step(db, iid):
    """The first step that has not decided yet — the person it is currently with. None once every step has decided."""
    for s in _invoice_steps(db, iid):
        if s["status"] == "pending":
            return s
    return None

def _invoice_step_user_ids(db, iid):
    return [s["user_id"] for s in _invoice_steps(db, iid) if s["user_id"]]

def _sync_invoice_from_steps(db, iid):
    """Keep the invoice's status in step with its chain: Rejected as soon as any step rejects, Approved once every step has approved, Pending while any step is still waiting."""
    steps = _invoice_steps(db, iid)
    if not steps:
        return
    if any(s["status"] == "rejected" for s in steps):
        new_status = "rejected"
    elif all(s["status"] == "approved" for s in steps):
        new_status = "approved"
    else:
        new_status = "pending"
    db.execute("UPDATE invoices SET status=?,updated_at=datetime('now','localtime') WHERE id=?", (new_status, iid))

def _invoice_chain_people(db):
    """Everyone a step in an invoice chain can be sent to: active, approved users in ANY department. Department admins first in each department, then by name."""
    return db.execute("SELECT id, full_name, designation, is_dept_admin, department_id FROM users "
                      "WHERE is_active=1 AND is_deleted=0 AND approval_status='approved' "
                      "ORDER BY department_id, is_dept_admin DESC, full_name").fetchall()

def _invoice_chain_depts(db):
    return db.execute("SELECT id, name FROM departments ORDER BY id").fetchall()

def _parse_invoice_chain(form, people):
    """Read the three step rows (stepN_role / stepN_user) from the form. Returns (chain, error): chain is a list of (role, user_id) in order. At least one step must be chosen, no person twice, and every person must be one of the chain people."""
    chain = []
    seen = set()
    ids = {p["id"] for p in people}
    for i in (1, 2, 3):
        role = (form.get(f"step{i}_role") or "none").strip().lower()
        if role == "none":
            continue
        if role not in INVOICE_STEP_ROLES:
            return None, "Choose a role for each step: None, Checked By, Approved By or Authorised By."
        try:
            uid = int(form.get(f"step{i}_user") or 0)
        except ValueError:
            uid = 0
        if uid not in ids:
            return None, "Choose a person for each step."
        if uid in seen:
            return None, "Choose a different person for each step."
        seen.add(uid)
        chain.append((role, uid))
    if not chain:
        return None, "Choose at least one step — who approves this invoice?"
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

def _save_invoice_chain(db, iid, chain):
    db.execute("DELETE FROM invoice_steps WHERE invoice_id=?", (iid,))
    for pos, (role, uid) in enumerate(chain, start=1):
        db.execute("INSERT INTO invoice_steps(invoice_id,position,role,user_id) VALUES (?,?,?,?)", (iid, pos, role, uid))

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

def _can_act_invoice(db, user, inv):
    """Only the person whose turn it is in the chain can approve or reject, and only while the invoice is Pending (the chain is still running)."""
    if inv["status"] != "pending":
        return False
    step = _current_invoice_step(db, inv["id"])
    return bool(step and step["user_id"] == user["id"])

def _notify_invoice_watchers(db, inv, iid, text, link):
    """The invoice's department admins are told, except the owner and the chain people — those were already told directly in the same action. A dept-admin actor is also told to the portal admin and permission users above them, a permission-user actor to the portal admin."""
    _admins = [r[0] for r in db.execute(
        "SELECT id FROM users WHERE department_id=? AND is_dept_admin=1 AND is_active=1",
        (inv["department_id"],))]
    _told = {inv["owner_id"]} | set(_invoice_step_user_ids(db, iid))
    notify(db, [uid for uid in _admins if uid not in _told], text, link, skip=g.user["id"])
    if _is_dept_admin(g.user):
        notify_dept_task(db, g.user, text, link)
    elif is_portal_admin(g.user):
        notify_admin_task(db, g.user, text, link)

def _sign_invoice_step(iid):
    """The person whose turn it is ticks "Use my signature": their saved signature is copied onto the invoice under their step's role. They must have used their signature before they can approve or reject."""
    db = get_db(); inv = _invoice(db, iid)
    if not _can_act_invoice(db, g.user, inv):
        abort(403)
    step = _current_invoice_step(db, iid)
    label = INVOICE_STEP_ROLES.get(step["role"], step["role"]) if step else ""
    if not request.form.get("use_my_signature"):
        flash("Tick 'Use my signature' to use the signature you saved in My settings.", "error")
        return redirect(url_for("invoices.detail", iid=iid))
    name = _use_my_signature_for("inv_signatures")
    if not name:
        flash("You haven't uploaded a signature yet — upload one in My settings first.", "error")
        return redirect(url_for("invoices.detail", iid=iid))
    if step["signature_path"]:
        try:
            old = os.path.join(config.UPLOAD_DIR, "inv_signatures", os.path.basename(step["signature_path"]))
            if os.path.exists(old):
                os.remove(old)
        except Exception:
            pass
    db.execute("UPDATE invoice_steps SET signature_path=?,signature_at=datetime('now','localtime') WHERE id=?", (name, step["id"]))
    log(db, "invoice_step_signature", f"{inv['number']} step {step['position']} {step['role']}")
    db.commit()
    flash(f"Your signature has been added under {label}. You can now approve or reject the invoice.", "ok")
    return redirect(url_for("invoices.detail", iid=iid))

def _decide_invoice(iid):
    """The person whose turn it is approves or rejects the invoice. They must have ticked "Use my signature" first. Approving moves it to the next step until the last step approves (status Approved, and the APPROVED seal appears on the PDF). Rejecting ends it at once (status Rejected, and the REJECTED stamp appears on the PDF)."""
    db = get_db(); inv = _invoice(db, iid)
    if not _can_act_invoice(db, g.user, inv):
        abort(403)
    step = _current_invoice_step(db, iid)
    steps = _invoice_steps(db, iid)
    label = INVOICE_STEP_ROLES.get(step["role"], step["role"]) if step else ""
    is_last = bool(step) and step["position"] == len(steps)
    new_status = (request.form.get("status") or "").strip()
    if new_status not in ("approved", "rejected"):
        flash("Choose a status: Approved or Rejected.", "error")
        return redirect(url_for("invoices.detail", iid=iid))
    if not step or not step["signature_path"]:
        flash(f"Use your signature first — you can only save the status once your signature is under {label}.", "error")
        return redirect(url_for("invoices.detail", iid=iid))
    db.execute("UPDATE invoice_steps SET status=? WHERE id=?", (new_status, step["id"]))
    _sync_invoice_from_steps(db, iid)
    log(db, "invoice_status", f"{inv['number']} step {step['position']} -> {new_status}")
    nxt = _current_invoice_step(db, iid)
    nxt_name = nxt["full_name"] if nxt else ""
    verb = "approved" if new_status == "approved" else "rejected"
    if new_status == "approved" and not is_last:
        notify(db, [nxt["user_id"]] if nxt else [],
               f"{g.user['full_name']} approved the invoice {inv['number']} and sent it to you to {INVOICE_STEP_VERBS[nxt['role']]}.",
               url_for("invoices.detail", iid=iid), skip=g.user["id"])
        notify(db, [inv["owner_id"]],
               f"{g.user['full_name']} approved your invoice {inv['number']} — it is now with {nxt_name}.",
               url_for("invoices.detail", iid=iid), skip=g.user["id"])
        for _s in steps:
            if _s["position"] < step["position"] and _s["user_id"] and _s["user_id"] != inv["owner_id"]:
                notify(db, [_s["user_id"]],
                       f"{g.user['full_name']} approved the invoice {inv['number']} — it is now with {nxt_name}.",
                       url_for("invoices.detail", iid=iid), skip=g.user["id"])
        _notify_invoice_watchers(db, inv, iid,
                                 f"{g.user['full_name']} approved the invoice {inv['number']} — it is now with {nxt_name}.",
                                 url_for("invoices.detail", iid=iid))
    else:
        # A final approval or a rejection: the owner is told directly, and
        # so is everyone who already decided.
        notify(db, [inv["owner_id"]],
               f"{g.user['full_name']} {verb} your invoice {inv['number']}.",
               url_for("invoices.detail", iid=iid), skip=g.user["id"])
        for _s in steps:
            if _s["position"] < step["position"] and _s["user_id"] and _s["user_id"] != inv["owner_id"]:
                notify(db, [_s["user_id"]],
                       f"{g.user['full_name']} {verb} the invoice {inv['number']}.",
                       url_for("invoices.detail", iid=iid), skip=g.user["id"])
        _notify_invoice_watchers(db, inv, iid,
                                 f"{g.user['full_name']} {verb} the invoice {inv['number']}.",
                                 url_for("invoices.detail", iid=iid))
    db.commit()
    flash(f"Invoice {verb}.", "ok")
    return redirect(url_for("invoices.detail", iid=iid))
