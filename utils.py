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
