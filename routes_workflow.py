"""
routes_workflow.py - notifications, comments/suggestions, handovers (transfers) and
requests that need approval.

Used by: app.py (registers it).   Uses: auth.py, core.py, routes_records.py, models.py
Templates: notifications, transfers, requests, request_form.
"""
import config
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from auth import login_required
from core import (EDIT_LEVELS, MANAGE_LEVELS, approver_ids, create_transfer, notify, resolve_transfer)
from models import get_db, log
from routes_records import _load as load_record

bp = Blueprint("flow", __name__)


# ---------------------------------------------------------------- notifications
@bp.route("/notifications")
@login_required
def notifications():
    db = get_db()
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100",
                      (g.user["id"],)).fetchall()
    shown = [dict(r) for r in rows]
    db.execute("UPDATE notifications SET read_at=datetime('now','localtime') WHERE user_id=? AND read_at IS NULL",
               (g.user["id"],))
    db.commit()
    return render_template("notifications.html", rows=shown, warn_days=g.user["warn_days"],
                           choices=config.WARN_DAY_CHOICES, hour=config.REMINDER_HOUR)


@bp.route("/notifications/settings", methods=["POST"])
@login_required
def notification_settings():
    """How many days ahead this person is warned about their reminder dates (1, 3 or 7)."""
    days = request.form.get("warn_days", type=int)
    db = get_db()
    if days in config.WARN_DAY_CHOICES:
        db.execute("UPDATE users SET warn_days=? WHERE id=?", (days, g.user["id"]))
        db.commit()
        flash(f"Saved. You will be warned {days} day{'' if days == 1 else 's'} ahead, "
              "one day before and on the day itself.", "ok")
    else:
        flash("Choose 1, 3 or 7 days.", "error")
    return redirect(url_for("flow.notifications"))


@bp.route("/notifications/clear", methods=["POST"])
@login_required
def notifications_clear():
    db = get_db()
    db.execute("DELETE FROM notifications WHERE user_id=?", (g.user["id"],))
    db.commit()
    return redirect(url_for("flow.notifications"))


# ---------------------------------------------------------------- comments and suggestions
@bp.route("/records/<int:rid>/comments", methods=["POST"])
@login_required
def add_comment(rid):
    rec, level = load_record(rid, "view")
    text = (request.form.get("text") or "").strip()[:1000]
    if not text:
        flash("Write something first.", "error")
        return redirect(url_for("records.detail", rid=rid))
    db = get_db()
    # Supervisors and viewers cannot edit, so what they write is a suggestion.
    kind = "suggestion" if level in ("supervisor", "viewer", "shared_view") else "comment"
    db.execute("INSERT INTO comments(record_id,user_id,kind,text) VALUES (?,?,?,?)", (rid, g.user["id"], kind, text))
    earlier = [r[0] for r in db.execute("SELECT DISTINCT user_id FROM comments WHERE record_id=?", (rid,))]
    label = "a suggestion" if kind == "suggestion" else "a comment"
    notify(db, [rec["owner_id"]] + earlier, f"{g.user['full_name']} wrote {label} on a record.",
           f"/records/{rid}", skip=g.user["id"])
    log(db, "comment_add", f"record {rid} ({kind})")
    db.commit()
    flash("Your suggestion was sent." if kind == "suggestion" else "Comment added.", "ok")
    return redirect(url_for("records.detail", rid=rid) + "#comments")


@bp.route("/comments/<int:cid>/delete", methods=["POST"])
@login_required
def delete_comment(cid):
    db = get_db()
    row = db.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
    if row is None:
        abort(404)
    if row["user_id"] != g.user["id"] and g.user["role"] != "admin":
        abort(403)
    db.execute("DELETE FROM comments WHERE id=?", (cid,))
    db.commit()
    return redirect(url_for("records.detail", rid=row["record_id"]) + "#comments")


# ---------------------------------------------------------------- handover (transfer)
@bp.route("/records/<int:rid>/transfer", methods=["POST"])
@login_required
def start_transfer(rid):
    rec, _level = load_record(rid, "manage")
    db = get_db()
    to_id = request.form.get("to_user", type=int)
    now = bool(request.form.get("immediately")) and g.user["role"] == "admin"
    error = create_transfer(db, g.user, rec, to_id, request.form.get("note"), immediately=now)
    if error:
        db.rollback()
        flash(error, "error")
    else:
        log(db, "transfer_start", f"record {rid} to user {to_id}")
        db.commit()
        flash("Done. The record now belongs to the new owner." if now else
              "The handover was sent. The new owner must accept it.", "ok")
    return redirect(url_for("records.detail", rid=rid))


@bp.route("/transfers")
@login_required
def transfers():
    db = get_db()
    base = ("SELECT t.*, fu.full_name AS from_name, tu.full_name AS to_name FROM transfers t "
            "JOIN users fu ON fu.id=t.from_user JOIN users tu ON tu.id=t.to_user ")
    incoming = db.execute(base + "WHERE t.status='pending' AND t.to_user=? ORDER BY t.id DESC", (g.user["id"],)).fetchall()
    if g.user["role"] == "admin":
        outgoing = db.execute(base + "WHERE t.status='pending' AND t.to_user != ? ORDER BY t.id DESC",
                              (g.user["id"],)).fetchall()
    else:
        outgoing = db.execute(base + "WHERE t.status='pending' AND t.from_user=? ORDER BY t.id DESC",
                              (g.user["id"],)).fetchall()
    recent = db.execute(base + "WHERE t.status != 'pending' AND (t.from_user=? OR t.to_user=?) "
                        "ORDER BY t.id DESC LIMIT 30", (g.user["id"], g.user["id"])).fetchall()
    return render_template("transfers.html", incoming=incoming, outgoing=outgoing, recent=recent)


@bp.route("/transfers/<int:tid>/<action>", methods=["POST"])
@login_required
def transfer_action(tid, action):
    db = get_db()
    tr = db.execute("SELECT * FROM transfers WHERE id=? AND status='pending'", (tid,)).fetchone()
    if tr is None or action not in ("accept", "decline", "cancel"):
        abort(404)
    if action in ("accept", "decline") and tr["to_user"] != g.user["id"]:
        abort(403)
    if action == "cancel" and tr["from_user"] != g.user["id"] and g.user["role"] != "admin":
        abort(403)
    resolve_transfer(db, g.user, tr, action)
    log(db, "transfer_" + action, f"record {tr['record_id']}")
    db.commit()
    flash({"accept": "You are now the owner of the record.", "decline": "Handover declined.",
           "cancel": "Handover cancelled."}[action], "ok")
    return redirect(url_for("flow.transfers"))


# ---------------------------------------------------------------- requests that need approval
KINDS = ("new_item", "repair", "other")


def _can_review(db, user, req):
    """Admins review everything; a department admin reviews requests of their own department."""
    if req["requester_id"] == user["id"]:
        return False
    return user["role"] == "admin" or (user["is_dept_admin"] and req["department_id"] == user["department_id"])


@bp.route("/requests")
@login_required
def requests_page():
    db = get_db()
    base = ("SELECT q.*, u.full_name AS requester_name, d.name AS department_name, "
            "(SELECT full_name FROM users WHERE id=q.decided_by) AS decider_name "
            "FROM requests q JOIN users u ON u.id=q.requester_id LEFT JOIN departments d ON d.id=q.department_id ")
    mine = db.execute(base + "WHERE q.requester_id=? ORDER BY q.id DESC LIMIT 100", (g.user["id"],)).fetchall()
    reviewer = g.user["role"] == "admin" or g.user["is_dept_admin"]
    to_review = []
    if reviewer:
        if g.user["role"] == "admin":
            to_review = db.execute(base + "WHERE q.requester_id != ? ORDER BY (q.status='pending') DESC, q.id DESC LIMIT 100",
                                   (g.user["id"],)).fetchall()
        else:
            to_review = db.execute(base + "WHERE q.department_id=? AND q.requester_id != ? "
                                   "ORDER BY (q.status='pending') DESC, q.id DESC LIMIT 100",
                                   (g.user["department_id"], g.user["id"])).fetchall()
    return render_template("requests.html", mine=mine, to_review=to_review, reviewer=reviewer,
                           tab=request.args.get("tab", "review" if to_review else "mine"))


@bp.route("/requests/new", methods=["GET", "POST"])
@login_required
def request_new():
    if request.method == "POST":
        kind = request.form.get("kind", "other")
        title = (request.form.get("title") or "").strip()[:150]
        details = (request.form.get("details") or "").strip()[:2000]
        if kind not in KINDS or not title:
            flash("Choose a type and write a short title.", "error")
        else:
            db = get_db()
            db.execute("INSERT INTO requests(requester_id,department_id,kind,title,details) VALUES (?,?,?,?,?)",
                       (g.user["id"], g.user["department_id"], kind, title, details))
            notify(db, approver_ids(db, g.user["department_id"]),
                   f"New request from {g.user['full_name']}: {title}", "/requests", skip=g.user["id"])
            log(db, "request_new", title)
            db.commit()
            flash("Your request was sent for approval.", "ok")
            return redirect(url_for("flow.requests_page", tab="mine"))
    return render_template("request_form.html", form=request.form)


@bp.route("/requests/<int:qid>/decide", methods=["POST"])
@login_required
def request_decide(qid):
    db = get_db()
    req = db.execute("SELECT * FROM requests WHERE id=? AND status='pending'", (qid,)).fetchone()
    if req is None:
        abort(404)
    if not _can_review(db, g.user, req):
        abort(403)
    decision = "approved" if request.form.get("decision") == "approve" else "rejected"
    note = (request.form.get("note") or "").strip()[:300]
    db.execute("UPDATE requests SET status=?, decided_by=?, decided_at=datetime('now','localtime'), decision_note=? "
               "WHERE id=?", (decision, g.user["id"], note, qid))
    notify(db, [req["requester_id"]], f"Your request \"{req['title']}\" was {decision}.", "/requests", skip=g.user["id"])
    log(db, "request_" + decision, req["title"])
    db.commit()
    flash(f"Request {decision}.", "ok")
    return redirect(url_for("flow.requests_page", tab="review"))


@bp.route("/requests/<int:qid>/cancel", methods=["POST"])
@login_required
def request_cancel(qid):
    db = get_db()
    req = db.execute("SELECT * FROM requests WHERE id=? AND requester_id=? AND status='pending'",
                     (qid, g.user["id"])).fetchone()
    if req is None:
        abort(404)
    db.execute("UPDATE requests SET status='cancelled' WHERE id=?", (qid,))
    db.commit()
    flash("Request cancelled.", "ok")
    return redirect(url_for("flow.requests_page", tab="mine"))
