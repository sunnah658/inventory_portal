"""
routes_workflow.py - notifications (bell), the reminder-days setting, and comments/suggestions.

Used by: app.py (registers it).   Uses: auth.py, core.py, routes_records.py, models.py
Templates: notifications.
"""
import config
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from auth import login_required
from utils import is_portal_admin
from core import EDIT_LEVELS, MANAGE_LEVELS, notify
from models import get_db, log
from routes_records import _load as load_record

bp = Blueprint("flow", __name__)


# ---------------------------------------------------------------- notifications
@bp.route("/notifications")
@login_required
def notifications():
    # Opening this page must NOT mark anything read: a user who only glances
    # at the list would lose the "New" badge and the bell count. Read state
    # changes only through the "Mark all as read" button below.
    db = get_db()
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100",
                      (g.user["id"],)).fetchall()
    shown = [dict(r) for r in rows]
    return render_template("notifications.html", rows=shown, warn_days=g.user["warn_days"],
                           choices=config.WARN_DAY_CHOICES, hour=config.REMINDER_HOUR)


@bp.route("/notifications/<int:nid>/open")
@login_required
def notification_open(nid):
    """Clicking a notification marks just that one read, then takes the user
    to the page it points at (2026-11-14) — so nobody has to press \"Mark all
    as read\" separately. A notification that is not this user's, or one with
    no page of its own, goes back to the notifications list."""
    db = get_db()
    row = db.execute("SELECT link FROM notifications WHERE id=? AND user_id=?",
                     (nid, g.user["id"])).fetchone()
    if row is None:
        abort(404)
    db.execute("UPDATE notifications SET read_at=datetime('now','localtime') WHERE id=? AND user_id=?",
               (nid, g.user["id"]))
    db.commit()
    link = (row["link"] or "").strip()
    if link.startswith("/"):
        return redirect(link)
    return redirect(url_for("flow.notifications"))


@bp.route("/notifications/mark-read", methods=["POST"])
@login_required
def notifications_mark_read():
    db = get_db()
    db.execute("UPDATE notifications SET read_at=datetime('now','localtime') WHERE user_id=? AND read_at IS NULL",
               (g.user["id"],))
    db.commit()
    return redirect(url_for("flow.notifications"))


@bp.route("/notifications/mark-selected", methods=["POST"])
@login_required
def notifications_mark_selected():
    """Mark only the ticked notifications read (the Select button on the page
    shows the tick boxes). Ids that are not this user's are ignored."""
    db = get_db()
    ids = [int(x) for x in request.form.getlist("nid") if x.isdigit()]
    if ids:
        db.execute("UPDATE notifications SET read_at=datetime('now','localtime') WHERE user_id=? AND id IN (%s)"
                   % ",".join("?" * len(ids)), (g.user["id"], *ids))
        db.commit()
    return redirect(url_for("flow.notifications"))


@bp.route("/notifications/clear-selected", methods=["POST"])
@login_required
def notifications_clear_selected():
    """Clear (delete) only the ticked notifications. Ids that are not this
    user's are ignored."""
    db = get_db()
    ids = [int(x) for x in request.form.getlist("nid") if x.isdigit()]
    if ids:
        db.execute("DELETE FROM notifications WHERE user_id=? AND id IN (%s)"
                   % ",".join("?" * len(ids)), (g.user["id"], *ids))
        db.commit()
    return redirect(url_for("flow.notifications"))


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
    if row["user_id"] != g.user["id"] and not is_portal_admin(g.user):
        abort(403)
    db.execute("DELETE FROM comments WHERE id=?", (cid,))
    db.commit()
    return redirect(url_for("records.detail", rid=row["record_id"]) + "#comments")
