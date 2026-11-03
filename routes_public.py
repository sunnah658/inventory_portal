"""
routes_public.py - public QR links: anyone who scans the code sees ONLY the fields the
owner chose, read-only, without logging in.

Used by: app.py (registers it).   Uses: core.py, auth.py, routes_records.py, models.py
Templates: public_view, public_links, public_link_form, qr_label.

Safety rules built in: long random codes (cannot be guessed), only chosen fields, no
history/attachments/repairs, a switch to turn a link off, a "new code" button that kills
the old printed QR, a rate limit per computer, and 'noindex' for search engines.
"""
import time
from collections import defaultdict, deque

import segno
from flask import (Blueprint, abort, flash, g, redirect, render_template, request, url_for)

import config
from auth import login_required
from core import (MANAGE_LEVELS, access_level, get_record, names_for_records, new_token,
                  public_fields_of, public_view, rec_select, summary_of, get_columns, values_for)
from models import get_db, log
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
    items = [{"rows": public_view(db, r, fields), "dept": r["department_name"]} for r in recs]
    db.execute("UPDATE public_links SET views=views+1 WHERE id=?", (link["id"],))
    db.commit()
    title = link["title"] or (items[0]["rows"][0][1] if items and items[0]["rows"] else "")
    return render_template("public_view.html", link=link, items=items, title=title)


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
        fields = _clean_fields(db, [rid], request.form)
        if not fields:
            flash("Tick at least one field to show.", "error")
            return redirect(url_for("records.detail", rid=rid) + "#public")
        if link is None:
            lid = db.execute("INSERT INTO public_links(token,owner_id,kind,fields) VALUES (?,?,'single',?)",
                             (new_token(), rec["owner_id"], "\n".join(fields))).lastrowid
            db.execute("INSERT INTO public_link_records(link_id,record_id) VALUES (?,?)", (lid, rid))
        else:
            db.execute("UPDATE public_links SET fields=?, enabled=1 WHERE id=?", ("\n".join(fields), link["id"]))
        log(db, "public_qr_on", f"record {rid}: {', '.join(fields)}")
        flash("The public QR is on. Anyone with the link sees only the ticked fields.", "ok")
    elif link is not None and action == "off":
        db.execute("UPDATE public_links SET enabled=0 WHERE id=?", (link["id"],))
        log(db, "public_qr_off", f"record {rid}")
        flash("The public QR is off. Scanning it shows nothing.", "ok")
    elif link is not None and action == "regenerate":
        db.execute("UPDATE public_links SET token=?, regenerated_at=datetime('now','localtime') WHERE id=?",
                   (new_token(), link["id"]))
        log(db, "public_qr_new_code", f"record {rid}")
        flash("New code created. Old printed QR codes no longer work, print the new one.", "ok")
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
    where, params = ("", []) if g.user["role"] == "admin" else ("WHERE pl.owner_id=?", [g.user["id"]])
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
        fields = _clean_fields(db, ids, request.form)
        title = (request.form.get("title") or "").strip()[:100]
        if not fields or not title:
            flash("Write a title and tick at least one field.", "error")
        else:
            lid = db.execute("INSERT INTO public_links(token,owner_id,title,kind,fields) VALUES (?,?,?,'group',?)",
                             (new_token(), g.user["id"], title, "\n".join(fields))).lastrowid
            for rid in ids:
                db.execute("INSERT INTO public_link_records(link_id,record_id) VALUES (?,?)", (lid, rid))
            log(db, "public_qr_group", f"{len(ids)} records: {title}")
            db.commit()
            flash("One public QR was created for the selected records.", "ok")
            return redirect(url_for("public.link_qr", lid=lid))
    return render_template("public_link_form.html", link=None, ids=",".join(map(str, ids)), count=len(ids),
                           names=names_for_records(db, ids), chosen=set(), title=request.form.get("title", ""))


def _own_link(lid):
    db = get_db()
    link = db.execute("SELECT * FROM public_links WHERE id=?", (lid,)).fetchone()
    if link is None or (link["owner_id"] != g.user["id"] and g.user["role"] != "admin"):
        abort(404)
    return link


@bp.route("/public-links/<int:lid>", methods=["GET", "POST"])
@login_required
def link_edit(lid):
    link = _own_link(lid)
    db = get_db()
    ids = [r[0] for r in db.execute("SELECT record_id FROM public_link_records WHERE link_id=?", (lid,))]
    if request.method == "POST":
        fields = _clean_fields(db, ids, request.form)
        title = (request.form.get("title") or "").strip()[:100]
        if not fields:
            flash("Tick at least one field.", "error")
        else:
            db.execute("UPDATE public_links SET fields=?, title=? WHERE id=?", ("\n".join(fields), title or link["title"], lid))
            log(db, "public_qr_edit", f"link {lid}")
            db.commit()
            flash("Saved.", "ok")
            return redirect(url_for("public.links"))
    return render_template("public_link_form.html", link=link, ids="", count=len(ids),
                           names=names_for_records(db, ids), chosen=set(public_fields_of(link)), title=link["title"] or "")


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
        db.execute("UPDATE public_links SET token=?, regenerated_at=datetime('now','localtime') WHERE id=?",
                   (new_token(), lid))
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
    item = {"id": "", "title": link["title"] or "Public record", "dept": "Public QR", "svg": _qr_svg(url), "url": url}
    return render_template("qr_label.html", items=[item], many=False)
