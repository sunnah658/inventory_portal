"""
routes_public.py - public QR links: anyone who scans the code sees ONLY the fields the
owner chose (or the full record, if the owner chose that), read-only, without logging in.
Every public QR gets a unique code HRC-0, HRC-1 ... printed under it. Any logged-in person can
type that code in a search bar to see the same information and download it as a PDF.

Used by: app.py (registers it).   Uses: core.py, auth.py, routes_records.py, models.py
Templates: public_view, public_links, public_link_form, qr_label, code_page.

Safety rules built in: long random codes (cannot be guessed), only chosen fields, no
history/attachments/repairs, a switch to turn a link off, a "new code" button that kills
the old printed QR, a rate limit per computer, and 'noindex' for search engines.
"""
import time
from collections import defaultdict, deque

import segno
from flask import (Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for)

import config
from auth import login_required
from utils import is_portal_admin
import exports
from core import (MANAGE_LEVELS, access_level, create_public_link, display_code, get_record, names_for_records, new_random_code_text, new_token,
                  parse_code_text, public_fields_of, public_view, rec_select)
from models import get_db, log, setting_get
from routes_records import _load as load_record

bp = Blueprint("public", __name__)
_HITS = defaultdict(deque)          # computer -> times of its recent requests


def _rate_ok(ip):
    """False when one computer asks for public pages too often."""
    now, hits = time.time(), _HITS[ip]
    while hits and hits[0] < now - 60:
        hits.popleft()
    if len(hits) >= config.PUBLIC_RATE_PER_MIN:
        return False
    hits.append(now)
    return True


def _qr_svg(url):
    return segno.make(url, error="m").svg_inline(scale=4, border=1, dark="#10283a", omitsize=True)


def _clean_fields(db, record_ids, form):
    """The chosen field names, limited to names that really exist for those records."""
    allowed = {n.lower() for n in names_for_records(db, record_ids)}
    return [f for f in dict.fromkeys(x.strip().lower() for x in form.getlist("fields")) if f in allowed]


# ---------------------------------------------------------------- the public page
@bp.route("/p/<token>")
def view(token):
    if not _rate_ok(request.remote_addr):
        return render_template("public_message.html", code=429,
                               message="Too many requests. Please wait a minute."), 429
    db = get_db()
    link = db.execute("SELECT * FROM public_links WHERE token=?", (token,)).fetchone()
    if link is None:
        return render_template("public_message.html", code=404, message="This QR code is not valid."), 404
    if not link["enabled"]:
        return render_template("public_message.html", code=410, message="This QR code is no longer active."), 410
    recs = db.execute(rec_select() + " JOIN public_link_records plr ON plr.record_id=r.id "
                      "WHERE plr.link_id=? AND r.deleted_at IS NULL ORDER BY r.id", (link["id"],)).fetchall()
    # A logged-in person who may open the record goes to the full record instead.
    if g.user is not None and link["kind"] == "single" and recs and access_level(db, g.user, recs[0]):
        return redirect(url_for("records.detail", rid=recs[0]["id"]))
    fields = set(public_fields_of(link))
    items = [{"rows": public_view(db, r, fields, bool(link["full_record"])), "dept": r["department_name"]} for r in recs]
    db.execute("UPDATE public_links SET views=views+1 WHERE id=?", (link["id"],))
    db.commit()
    title = link["title"] or (items[0]["rows"][0][1] if items and items[0]["rows"] else "")
    return render_template("public_view.html", link=link, items=items, title=title, code=display_code(link))


# ---------------------------------------------------------------- find a QR by its code (people who are logged in)
def _link_by_code(db, code):
    """Find a public link by its shown code: ONLY the random HRC-##### code_text.

    The old sequential code_no is never accepted any more: it was guessable
    (HRC-0, HRC-1, ...), so a link whose random code is not known must not
    open through its sequential number. Every link already has a random
    code_text (the upgrade in models.py backfills any link missing one),
    and the token link (/p/<token>) is unaffected.
    Returns (wanted_code, link) with link None when nothing matches."""
    wanted = parse_code_text(code)
    if not wanted:
        # a bare 5-digit number is a random code, e.g. 48392 -> HRC-48392
        s = (code or "").strip()
        if s.isdigit() and len(s) == 5:
            wanted = f"HRC-{s}"
    if not wanted:
        return None, None
    link = db.execute("SELECT * FROM public_links WHERE code_text=?", (wanted,)).fetchone()
    return wanted, link


def _link_items(db, link):
    recs = db.execute(rec_select() + " JOIN public_link_records plr ON plr.record_id=r.id "
                      "WHERE plr.link_id=? AND r.deleted_at IS NULL ORDER BY r.id", (link["id"],)).fetchall()
    fields = set(public_fields_of(link))
    return [{"rows": public_view(db, r, fields, bool(link["full_record"])), "dept": r["department_name"],
             "rid": r["id"]} for r in recs]


@bp.route("/code/<code>")
@login_required
def code_page(code):
    """Search result for a code such as HRC-48392: the information the owner made public."""
    db = get_db()
    wanted, link = _link_by_code(db, code)
    if link is None or not link["enabled"]:
        # One generic "not available" answer for a code that does not exist
        # and for a code whose owner switched it off: the two must not be
        # distinguishable, or a logged-in user could probe which codes exist.
        return render_template("code_page.html", code=wanted or code, status="unavailable", link=None, items=[]), 404
    items = _link_items(db, link)
    return render_template("code_page.html", code=display_code(link), status="ok", link=link, items=items,
                           title=link["title"] or (items[0]["rows"][0][1] if items and items[0]["rows"] else ""))


@bp.route("/code/<code>/pdf")
@login_required
def code_pdf(code):
    """The same information as a clean PDF: the shared fields only, no history."""
    db = get_db()
    _wanted, link = _link_by_code(db, code)
    if link is None or not link["enabled"]:
        abort(404)
    items = _link_items(db, link)
    wanted = display_code(link)
    sections = [((it["dept"] if len(items) > 1 else ""), ["Field", "Value"], [list(r) for r in it["rows"]] or [["", "Nothing to show"]])
                for it in items] or [("", ["Field", "Value"], [["", "This record is not available."]])]
    data = exports.document_pdf(f"{wanted}" + (f" · {link['title']}" if link["title"] else ""),
                                f"Printed by {g.user['full_name']}", sections,
                                setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME))
    log(db, "code_pdf", wanted)
    db.commit()
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{wanted}.pdf"'
    return resp


# ---------------------------------------------------------------- the "Search QR" tab (every logged-in person)
@bp.route("/search-qr")
@login_required
def search_qr():
    """A search box for the unique code (HRC-48392, hrc 48392 or just 48392). Shows the match with the buttons
    View record, Download PDF and Print. People only see what the owner made public for that code.
    Only the random 5-digit code is accepted; old sequential numbers are not."""
    db = get_db()
    q = (request.args.get("q") or "").strip()
    status, link, items, full_rid = None, None, [], None
    _wanted = None
    if q:
        _wanted = parse_code_text(q)
        if _wanted is None and q.isdigit() and len(q) == 5:
            _wanted = f"HRC-{q}"
        if _wanted is None:
            status = "bad"
        else:
            link = db.execute("SELECT * FROM public_links WHERE code_text=?", (_wanted,)).fetchone()
            if link is None:
                # invoice public code (login-only): HRC-##### -> invoice code page
                try:
                    _inv = db.execute("SELECT public_code FROM invoices WHERE public_code=?", (_wanted,)).fetchone()
                except Exception:
                    _inv = None
                if _inv is not None:
                    return redirect(url_for("invoices.code_page", code=_inv["public_code"]))
            if link is None or not link["enabled"]:
                # Same generic answer whether the code does not exist or is off.
                status = "unavailable"
                link = None
            else:
                status = "ok"
                items = _link_items(db, link)
                # a person who may open the whole record also gets a button for it
                if link["kind"] == "single" and items:
                    rec = get_record(db, items[0]["rid"])
                    if rec and access_level(db, g.user, rec):
                        full_rid = rec["id"]
    return render_template("search_qr.html", q=q, status=status, link=link, items=items,
                           code=display_code(link) if link is not None else (_wanted or ""), full_rid=full_rid,
                           title=(link["title"] if link and link["title"] else
                                  (items[0]["rows"][0][1] if items and items[0]["rows"] else "")))


# ---------------------------------------------------------------- one record: switch on the record page
@bp.route("/records/<int:rid>/public", methods=["POST"])
@login_required
def record_public(rid):
    rec, _level = load_record(rid, "manage")
    db = get_db()
    action = request.form.get("action", "save")
    link = db.execute("SELECT pl.* FROM public_links pl JOIN public_link_records plr ON plr.link_id=pl.id "
                      "WHERE plr.record_id=? AND pl.kind='single'", (rid,)).fetchone()
    if action == "save":
        full = bool(request.form.get("full_record"))
        fields = [] if full else _clean_fields(db, [rid], request.form)
        if not full and not fields:
            flash("Tick the fields to show, or choose to share the full record.", "error")
            return redirect(url_for("records.detail", rid=rid) + "#public")
        if link is None:
            lid = create_public_link(db, rec["owner_id"], "single", fields, full)
            db.execute("INSERT INTO public_link_records(link_id,record_id) VALUES (?,?)", (lid, rid))
            _row = db.execute("SELECT * FROM public_links WHERE id=?", (lid,)).fetchone(); code = display_code(_row)
        else:
            db.execute("UPDATE public_links SET fields=?, full_record=?, enabled=1 WHERE id=?",
                       ("\n".join(fields), 1 if full else 0, link["id"]))
            code = display_code(link)
        log(db, "public_qr_on", f"record {rid} {code}: " + ("full record" if full else ", ".join(fields)))
        flash(f"The public QR is on. Its code is {code}. Anyone with the link sees only "
              + ("the full record." if full else "the ticked fields."), "ok")
    elif link is not None and action == "off":
        db.execute("UPDATE public_links SET enabled=0 WHERE id=?", (link["id"],))
        log(db, "public_qr_off", f"record {rid}")
        flash("The public QR is off. Scanning it shows nothing.", "ok")
    elif link is not None and action == "regenerate":
        # Rotating the scan link must also rotate the HRC code itself:
        # otherwise the old code typed in search would still open the link.
        _new_code = new_random_code_text(db) or link["code_text"]
        db.execute("UPDATE public_links SET token=?, code_text=?, regenerated_at=datetime('now','localtime') WHERE id=?",
                   (new_token(), _new_code, link["id"]))
        log(db, "public_qr_new_code", f"record {rid} {_new_code}")
        flash(f"New code created: {_new_code}. Old printed QR codes and the old code no longer work, print the new one.", "ok")
    db.commit()
    return redirect(url_for("records.detail", rid=rid) + "#public")


# ---------------------------------------------------------------- many records: one QR for a group
def _manageable(db, ids):
    """Records of the id list the current user may manage."""
    out = []
    for rid in ids:
        rec = get_record(db, rid)
        if rec and not rec["deleted_at"] and access_level(db, g.user, rec) in MANAGE_LEVELS:
            out.append(rec)
    return out


@bp.route("/public-links")
@login_required
def links():
    db = get_db()
    where, params = ("", []) if is_portal_admin(g.user) else ("WHERE pl.owner_id=?", [g.user["id"]])
    rows = db.execute("SELECT pl.*, u.full_name AS owner_name, "
                      "(SELECT COUNT(*) FROM public_link_records WHERE link_id=pl.id) AS n "
                      "FROM public_links pl JOIN users u ON u.id=pl.owner_id " + where + " ORDER BY pl.id DESC",
                      params).fetchall()
    return render_template("public_links.html", rows=rows)


@bp.route("/public-links/new", methods=["GET", "POST"])
@login_required
def link_new():
    db = get_db()
    ids = [int(x) for x in (request.values.get("ids") or "").split(",") if x.strip().isdigit()]
    recs = _manageable(db, ids)
    if not recs:
        flash("Tick at least one of your records first.", "error")
        return redirect(url_for("records.list_records"))
    ids = [r["id"] for r in recs]
    if request.method == "POST":
        full = bool(request.form.get("full_record"))
        fields = [] if full else _clean_fields(db, ids, request.form)
        title = (request.form.get("title") or "").strip()[:100]
        if (not fields and not full) or not title:
            flash("Write a title and tick at least one field, or choose the full record.", "error")
        else:
            lid = create_public_link(db, g.user["id"], "group", fields, full, title)
            for rid in ids:
                db.execute("INSERT INTO public_link_records(link_id,record_id) VALUES (?,?)", (lid, rid))
            log(db, "public_qr_group", f"{len(ids)} records: {title}")
            db.commit()
            _row = db.execute("SELECT * FROM public_links WHERE id=?", (lid,)).fetchone()
            flash("One public QR was created for the selected records. Its code is "
                  + display_code(_row) + ".", "ok")
            return redirect(url_for("public.link_qr", lid=lid))
    return render_template("public_link_form.html", link=None, ids=",".join(map(str, ids)), count=len(ids),
                           names=names_for_records(db, ids), chosen=set(), title=request.form.get("title", ""), full=False)


def _own_link(lid):
    db = get_db()
    link = db.execute("SELECT * FROM public_links WHERE id=?", (lid,)).fetchone()
    if link is None or (link["owner_id"] != g.user["id"] and not is_portal_admin(g.user)):
        abort(404)
    return link


@bp.route("/public-links/<int:lid>", methods=["GET", "POST"])
@login_required
def link_edit(lid):
    link = _own_link(lid)
    db = get_db()
    ids = [r[0] for r in db.execute("SELECT record_id FROM public_link_records WHERE link_id=?", (lid,))]
    if request.method == "POST":
        full = bool(request.form.get("full_record"))
        fields = [] if full else _clean_fields(db, ids, request.form)
        title = (request.form.get("title") or "").strip()[:100]
        if not fields and not full:
            flash("Tick at least one field, or choose the full record.", "error")
        else:
            db.execute("UPDATE public_links SET fields=?, full_record=?, title=? WHERE id=?",
                       ("\n".join(fields), 1 if full else 0, title or link["title"], lid))
            log(db, "public_qr_edit", f"link {lid}")
            db.commit()
            flash("Saved.", "ok")
            return redirect(url_for("public.links"))
    return render_template("public_link_form.html", link=link, ids="", count=len(ids),
                           names=names_for_records(db, ids), chosen=set(public_fields_of(link)), title=link["title"] or "",
                           full=bool(link["full_record"]))


@bp.route("/public-links/<int:lid>/<action>", methods=["POST"])
@login_required
def link_action(lid, action):
    link = _own_link(lid)
    db = get_db()
    if action == "on":
        db.execute("UPDATE public_links SET enabled=1 WHERE id=?", (lid,))
    elif action == "off":
        db.execute("UPDATE public_links SET enabled=0 WHERE id=?", (lid,))
    elif action == "regenerate":
        _new_code = new_random_code_text(db) or link["code_text"]
        db.execute("UPDATE public_links SET token=?, code_text=?, regenerated_at=datetime('now','localtime') WHERE id=?",
                   (new_token(), _new_code, lid))
        log(db, "public_qr_regenerate", f"link {lid} {_new_code}")
        db.commit()
        flash(f"New code created: {_new_code}. The old code no longer works.", "ok")
        return redirect(url_for("public.links"))
    elif action == "delete":
        db.execute("DELETE FROM public_links WHERE id=?", (lid,))
    else:
        abort(404)
    log(db, "public_qr_" + action, f"link {lid}")
    db.commit()
    flash("Done.", "ok")
    return redirect(url_for("public.links"))


@bp.route("/public-links/<int:lid>/qr")
@login_required
def link_qr(lid):
    link = _own_link(lid)
    url = url_for("public.view", token=link["token"], _external=True)
    item = {"id": "", "title": link["title"] or "Public record", "dept": "Public QR", "svg": _qr_svg(url), "url": url,
            "code": display_code(link)}
    return render_template("qr_label.html", items=[item], many=False)
