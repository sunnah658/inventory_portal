"""
auth.py - login (with department), logout and change password.

Used by: app.py (registers it), every page file (login_required / admin_required).
Uses:    config.py, models.py

Login rule: a normal user must pick the department the admin assigned to them.
An admin may pick any department or "All departments".
Protection: a username is locked after 5 wrong passwords, a computer (IP address) after
20; every attempt is saved with its IP address; each login is a server-side session that
ends after 30 minutes without activity and can be ended by the admin.
"""
import secrets
from functools import wraps

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import config
from models import get_db, log
from security import (blocked_reason, create_session, password_problem, record_attempt,
                      revoke_session)

bp = Blueprint("auth", __name__)

GENERIC_ERROR = "Wrong username, password or department."


def login_required(view):
    """Page needs a logged-in user."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Page needs a logged-in admin."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("records.home"))
    db = get_db()
    departments = db.execute("SELECT id, name FROM departments ORDER BY name").fetchall()

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        dept = request.form.get("department") or ""
        ip = request.remote_addr

        reason = blocked_reason(db, username, ip)
        if reason:
            log(db, "login_blocked", "too many wrong attempts", username=username)
            db.commit()
            flash(reason, "error")
            return render_template("login.html", departments=departments, username=username)

        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        ok = bool(user and user["is_active"] and check_password_hash(user["password_hash"], password))
        if ok and user["role"] != "admin":
            ok = dept.isdigit() and int(dept) == user["department_id"]
        if ok and user["role"] == "admin":
            ok = dept == "all" or dept.isdigit()

        if not ok:
            record_attempt(db, username, ip, False)
            log(db, "login_failed", "wrong username, password or department", username=username)
            db.commit()
            flash(GENERIC_ERROR, "error")
            return render_template("login.html", departments=departments, username=username)

        record_attempt(db, username, ip, True)
        session.clear()
        session.permanent = True
        session["user_id"] = user["id"]
        session["sid"] = create_session(db, user["id"], ip, request.headers.get("User-Agent"))
        session["csrf"] = secrets.token_hex(16)
        g.user = user
        log(db, "login")
        db.commit()
        if user["must_change_password"]:
            return redirect(url_for("auth.change_password"))
        return redirect(url_for("records.home"))

    return render_template("login.html", departments=departments, username="")


@bp.route("/logout", methods=["POST"])
def logout():
    if g.user is not None:
        db = get_db()
        revoke_session(db, session.get("sid"))
        log(db, "logout")
        db.commit()
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current") or ""
        new = request.form.get("new") or ""
        again = request.form.get("again") or ""
        db = get_db()
        if not check_password_hash(g.user["password_hash"], current):
            flash("Your current password is not correct.", "error")
        elif password_problem(new, g.user["username"]):
            flash(password_problem(new, g.user["username"]), "error")
        elif new != again:
            flash("The two new passwords do not match.", "error")
        elif new == current:
            flash("Choose a password different from the old one.", "error")
        else:
            db.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                       (generate_password_hash(new), g.user["id"]))
            db.execute("UPDATE sessions SET revoked=1 WHERE user_id=? AND id != ?",
                       (g.user["id"], session.get("sid")))          # other logins of this user end
            log(db, "change_password")
            db.commit()
            flash("Password changed.", "ok")
            return redirect(url_for("records.home"))
    return render_template("change_password.html")
