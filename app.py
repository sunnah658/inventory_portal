"""
app.py - the start file of the portal. THE MOST IMPORTANT FILE: it connects all others.

Run with Docker:  docker compose up -d --build        (waitress runs "app:app")
Run for testing:  python app.py

What it does: creates the Flask app, creates/upgrades the database, registers the page
files (blueprints), and before every request: checks the login session (with the idle
timeout), the security token (CSRF), the light/dark theme, and the password-change rule.
It also adds the logo, company name and the bell counter to every page.
"""
import os
import secrets
import threading
import time
from datetime import datetime, timedelta

from flask import (Flask, abort, flash, g, make_response, redirect, render_template, request,
                   session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import models
from auth import bp as auth_bp
from branding import bp as brand_bp, logo_version
from core import design_rail, options_of, purge_expired, send_ddb_meeting_notifications, send_reminder_notifications, show_when
from models import get_db, setting_get
from utils import is_portal_admin, user_name_class
from routes_admin import bp as admin_bp
from routes_bulk import bp as bulk_bp
from routes_deptdb import bp as ddb_bp
from routes_invoices import bp as invoices_bp
from routes_public import bp as public_bp
from routes_records import bp as records_bp
from routes_workflow import bp as flow_bp
from security import check_session, purge_sessions, reauth_fresh

_last_purge = [0.0]       # when the recycle bin and old sessions were last cleaned
_last_reminders = [0.0]   # when the reminder notifications were last checked


def _reminder_loop():
    """Background helper: every 5 minutes send the reminder notifications that are due
    (from REMINDER_HOUR in the morning). Each message is sent once only."""
    while True:
        time.sleep(300)
        try:
            conn = models.connect()
            try:
                if send_reminder_notifications(conn) or send_ddb_meeting_notifications(conn):
                    conn.commit()
            finally:
                conn.close()
        except Exception as exc:                 # never let the helper stop
            print("reminder check failed:", exc, flush=True)


def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=config.get_secret_key(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.HTTPS_ONLY,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=config.SESSION_HOURS),
        MAX_CONTENT_LENGTH=config.MAX_REQUEST_MB * 1024 * 1024,
    )
    if config.BEHIND_PROXY:        # the Caddy HTTPS proxy tells us the real IP address and https
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    models.init_db()                 # create tables / upgrade an older database
    models.init_app(app)
    app.jinja_env.globals["options_of"] = options_of      # dropdown choices in templates
    def share_people():
        """Active people for the 'share with a person' choice in the bulk bar (once per request)."""
        if "share_people" not in g:
            g.share_people = get_db().execute(
                "SELECT u.id, u.full_name, u.username, d.name AS dept_name FROM users u "
                "LEFT JOIN departments d ON d.id=u.department_id WHERE u.is_active=1 "
                "ORDER BY d.name, u.full_name").fetchall()
        return g.share_people
    app.jinja_env.globals["share_people"] = share_people
    app.jinja_env.filters["showdt"] = show_when           # '2026-11-04 3:30 PM' in templates
    if os.environ.get("PORTAL_NO_SCHEDULER") != "1":      # tests switch the helper off
        threading.Thread(target=_reminder_loop, name="reminders", daemon=True).start()

    for blueprint in (auth_bp, records_bp, flow_bp, public_bp, bulk_bp, ddb_bp, admin_bp, brand_bp, invoices_bp):
        app.register_blueprint(blueprint)

    # ------------------------------------------------------------ before every request
    @app.before_request
    def load_user_and_check_csrf():
        """Who is logged in, theme, token check, clean-up, password change rule."""
        if request.endpoint == "static":
            return None
        db = get_db()
        g.user = None
        user_id, sid = session.get("user_id"), session.get("sid")
        if user_id:
            status = check_session(db, sid, user_id) if sid else "revoked"
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() if status == "ok" else None
            if row is not None and row["is_active"]:
                g.user = row
            else:
                session.clear()
                if status == "idle":
                    flash("You were logged out because of inactivity. Please log in again.", "error")

        theme = g.user["theme"] if g.user else request.cookies.get("theme", "auto")
        g.theme = theme if theme in ("light", "dark", "auto") else "auto"

        if request.method == "POST":                       # CSRF protection for every form
            token = session.get("csrf") or ""
            sent = request.form.get("csrf_token") or ""
            if not token or not secrets.compare_digest(token, sent):
                abort(400)

        if time.time() - _last_purge[0] > 3600:            # hourly clean-up
            _last_purge[0] = time.time()
            purge_expired(db)
            purge_sessions(db)
            db.commit()

        if g.user is not None:
            if time.time() - _last_reminders[0] > 300:     # also check when someone opens a page
                _last_reminders[0] = time.time()
                send_reminder_notifications(db)
                send_ddb_meeting_notifications(db)
                db.commit()
            if (g.user["must_change_password"]
                    and request.endpoint not in ("auth.change_password", "auth.logout", "brand.logo",
                                                 "brand.icon", "app_prefs")):
                return redirect(url_for("auth.change_password"))
        return None

    # ------------------------------------------------------------ light / dark theme
    @app.route("/prefs", methods=["POST"], endpoint="app_prefs")
    def prefs():
        """Save the light/dark choice (for the user, and in a cookie for the login page)."""
        theme = request.form.get("theme")
        resp = make_response(redirect(_safe_next(request.form.get("next"))))
        db = get_db()
        if theme in ("light", "dark", "auto"):
            resp.set_cookie("theme", theme, max_age=31536000, samesite="Lax")
            if g.user:
                db.execute("UPDATE users SET theme=? WHERE id=?", (theme, g.user["id"]))
        db.commit()
        return resp

    def _safe_next(url):
        return url if (url or "").startswith("/") and not url.startswith("//") else url_for("records.home")

    # ------------------------------------------------------------ values for every template
    @app.context_processor
    def inject_common():
        def csrf_token():
            if "csrf" not in session:
                session["csrf"] = secrets.token_hex(16)
            return session["csrf"]
        db = get_db()
        version = logo_version()
        # Stylesheet version: changes when style.css changes, so browsers fetch a
        # fresh stylesheet after an upgrade instead of reusing a cached copy.
        css_path = os.path.join(app.static_folder, "style.css")
        css_v = int(os.path.getmtime(css_path)) if os.path.exists(css_path) else 0
        data = {"csrf_token": csrf_token,
                "theme": g.get("theme", "auto"),
                "now_text": datetime.now().strftime("%d %b %Y %H:%M"),
                "company_name": setting_get(db, "company_name", config.DEFAULT_COMPANY_NAME),
                "logo_url": url_for("brand.logo", v=version), "icon_url": url_for("brand.icon", v=version),
                "css_v": css_v,
                "reauth_fresh": reauth_fresh(), "unread": 0,
                "can_reports": False, "has_view_tabs": False, "can_portal_admin": False, "user_name_class": user_name_class}
        user = g.get("user")
        if user is not None:
            data["unread"] = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL",
                                        (user["id"],)).fetchone()[0]
            data["can_reports"] = user["role"] == "admin" or bool(user["is_dept_admin"])
            data["can_portal_admin"] = is_portal_admin(user)
            data["user_name_class"] = user_name_class
            # Design 6 rail + chart data (follow-ups, recent rows, rows added this
            # week), scoped to the department/tab being viewed. Only data this
            # user is already allowed to see; {} when there is nothing to show.
            try:
                dept_arg = request.args.get("dept", type=int)
                tab_arg = request.args.get("tab", "")
                tab_id = int(tab_arg) if tab_arg and tab_arg.isdigit() else None
                data["design"] = design_rail(db, user, dept_arg, tab_id)
            except Exception:
                data["design"] = {}
        return data

    @app.template_filter("status_class")
    def status_class(value):
        """Colour of a status badge: g = green, a = amber, r = red."""
        v = (value or "").lower()
        if any(w in v for w in ("repair", "pending", "partial", "unpaid", "due", "stock", "open")):
            return "a"
        if any(w in v for w in ("damage", "reject", "overdue", "retired", "lost", "critical")):
            return "r"
        if any(w in v for w in ("use", "paid", "approved", "won", "active", "done")):
            return "g"
        return ""

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
        if config.HTTPS_ONLY:                                # tell browsers to use https only
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def error_page(code, message):
        return render_template("error.html", code=code, message=message), code

    @app.errorhandler(400)
    def bad_request(_e):
        return error_page(400, "This page has expired. Go back, refresh it and try again.")

    @app.errorhandler(403)
    def forbidden(_e):
        return error_page(403, "You do not have permission to open this page.")

    @app.errorhandler(404)
    def not_found(_e):
        return error_page(404, "This page was not found.")

    @app.errorhandler(413)
    def too_large(_e):
        return error_page(413, "The upload is too large.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
