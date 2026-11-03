"""
security.py - login protection, sessions with idle timeout, password rules, password
re-entry for dangerous actions.

Used by: auth.py (login, logout, change password), app.py (every request),
         routes_admin.py (dangerous actions, sessions page)
Uses:    config.py
"""
import secrets
import time

from flask import session
from werkzeug.security import check_password_hash

import config


# ------------------------------------------------------------------ password rules
def password_problem(password, username=""):
    """Returns a message when the password is too weak, otherwise None."""
    if len(password) < 8:
        return "The password must have at least 8 characters."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "The password needs both letters and numbers."
    if username and password.lower() == username.lower():
        return "The password must not be the same as the username."
    return None


# ------------------------------------------------------------------ login attempts
def record_attempt(db, username, ip, success):
    db.execute("INSERT INTO login_attempts(username, ip, success) VALUES (?,?,?)",
               ((username or "")[:100], ip, 1 if success else 0))


def blocked_reason(db, username, ip):
    """None when login may be tried, otherwise the message to show.

    * a username is locked after MAX_FAILED wrong passwords (LOCK_MINUTES)
    * a computer (IP address) is blocked after IP_MAX_FAILED wrong passwords from it
    Blocked attempts are not counted again, so the lock always ends by itself.
    """
    uname = (username or "").lower()
    row = db.execute(
        "SELECT COUNT(*) AS n, MAX(at) AS last FROM login_attempts WHERE lower(username)=? AND success=0 "
        "AND at > datetime('now','localtime','-15 minutes') AND id > COALESCE("
        "(SELECT MAX(id) FROM login_attempts WHERE lower(username)=? AND success=1), 0)",
        (uname, uname)).fetchone()
    if row["n"] >= config.MAX_FAILED and db.execute(
            "SELECT ?>datetime('now','localtime',?)", (row["last"], f"-{config.LOCK_MINUTES} minutes")).fetchone()[0]:
        return f"Too many wrong attempts. Try again in {config.LOCK_MINUTES} minutes."
    row = db.execute("SELECT COUNT(*) AS n, MAX(at) AS last FROM login_attempts WHERE ip=? AND success=0 "
                     "AND at > datetime('now','localtime','-30 minutes')", (ip,)).fetchone()
    if row["n"] >= config.IP_MAX_FAILED and db.execute(
            "SELECT ?>datetime('now','localtime',?)", (row["last"], f"-{config.IP_LOCK_MINUTES} minutes")).fetchone()[0]:
        return f"Too many failed logins from this computer. Try again in {config.IP_LOCK_MINUTES} minutes."
    return None


# ------------------------------------------------------------------ sessions
def create_session(db, user_id, ip, user_agent):
    sid = secrets.token_urlsafe(24)
    db.execute("INSERT INTO sessions(id,user_id,ip,user_agent) VALUES (?,?,?,?)",
               (sid, user_id, ip, (user_agent or "")[:200]))
    return sid


def check_session(db, sid, user_id):
    """'ok', 'idle' (no activity for IDLE_MINUTES) or 'revoked'/'missing'."""
    row = db.execute("SELECT revoked, (julianday('now','localtime')-julianday(last_seen))*1440 AS idle "
                     "FROM sessions WHERE id=? AND user_id=?", (sid, user_id)).fetchone()
    if row is None or row["revoked"]:
        return "revoked"
    if row["idle"] > config.IDLE_MINUTES:
        db.execute("UPDATE sessions SET revoked=1 WHERE id=?", (sid,))
        db.commit()
        return "idle"
    if row["idle"] > 1:                                   # write at most once a minute
        db.execute("UPDATE sessions SET last_seen=datetime('now','localtime') WHERE id=?", (sid,))
        db.commit()
    return "ok"


def revoke_session(db, sid):
    db.execute("UPDATE sessions SET revoked=1 WHERE id=?", (sid,))


def revoke_user_sessions(db, user_id):
    db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))


def purge_sessions(db):
    db.execute("DELETE FROM sessions WHERE last_seen < datetime('now','localtime','-2 days')")
    db.execute("DELETE FROM login_attempts WHERE at < datetime('now','localtime','-30 days')")


# ------------------------------------------------------------------ password re-entry
def reauth_fresh():
    """True when the admin typed the password a moment ago."""
    return session.get("reauth_until", 0) > time.time()


def reauth_ok(user, form):
    """Dangerous actions need the admin's own password (valid for REAUTH_SECONDS)."""
    if reauth_fresh():
        return True
    password = form.get("admin_password") or ""
    if password and check_password_hash(user["password_hash"], password):
        session["reauth_until"] = time.time() + config.REAUTH_SECONDS
        return True
    return False
