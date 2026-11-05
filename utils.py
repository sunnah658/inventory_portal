"""
utils.py - small helpers: CSV download, password generator, search escape, paging.

Used by: routes_records.py, routes_admin.py, import_users.py, core.py
"""
import csv
import io
import re
import secrets
from datetime import date

from flask import Response

_PASSWORD_CHARS = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_password(length=10):
    """Random temporary password (no look-alike characters such as 0/O or l/1)."""
    while True:
        password = "".join(secrets.choice(_PASSWORD_CHARS) for _ in range(length))
        if any(c.isalpha() for c in password) and any(c.isdigit() for c in password):
            return password          # always has letters and numbers (passes the password rule)


def _flag(row, name):
    """Read a flag from a SQLite Row or a dict, without crashing on old rows."""
    if row is None:
        return 0
    try:
        keys = row.keys()
    except Exception:
        keys = None
    if keys is not None and name not in keys:
        return 0
    try:
        return row[name]
    except Exception:
        return 0


def is_true_admin(user):
    """The original portal admin account (role 'admin'), not a delegated one."""
    return bool(user) and user["role"] == "admin" if user is not None else False


def is_portal_admin(user):
    """True portal admin OR a user given portal administrative permission."""
    if not user:
        return False
    if user["role"] == "admin":
        return True
    return bool(_flag(user, "can_portal_admin"))


def user_name_class(user):
    """Colour class for a person's name: green = active, yellow = locked/disabled,
    red = deleted (soft-deleted, in the Recycle Bin Users tab for 30 days).
    Accepts a user row, or a record/row carrying owner_is_deleted / owner_is_active."""
    if user is None:
        return ""
    try:
        keys = list(user.keys())
    except Exception:
        keys = list(user) if isinstance(user, dict) else []
    if "approval_status" in keys and user["approval_status"] == "pending":
        return ""
    if "is_deleted" in keys and user["is_deleted"]:
        return "user-deleted"
    if "owner_is_deleted" in keys and user["owner_is_deleted"]:
        return "user-deleted"
    if "owner_is_active" in keys:
        return "user-active" if user["owner_is_active"] else "user-locked"
    if "is_active" in keys:
        return "user-active" if user["is_active"] else "user-locked"
    return "user-active"


def like_pattern(text):
    """Turn a search word into a safe SQL LIKE pattern (used with ESCAPE '\\')."""
    return "%" + text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def safe_cell(value):
    """Stop Excel from running a cell that starts with = + - @ (CSV injection)."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text and text[0] in "=+-@\t\r" else text


def csv_response(header, rows, filename_prefix):
    """Build a CSV download that opens correctly in Excel (UTF-8 with BOM)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(c) for c in row])
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", filename_prefix).strip("_") or "export"
    resp = Response("\ufeff" + out.getvalue(), mimetype="text/csv")
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{name}_{date.today().isoformat()}.csv"'
    return resp


def page_info(total, page, per_page):
    """Return (page, pages, offset) with the page number kept inside the valid range."""
    pages = max(1, -(-total // per_page))
    page = min(max(page, 1), pages)
    return page, pages, (page - 1) * per_page
