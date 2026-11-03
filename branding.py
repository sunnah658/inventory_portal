"""
branding.py - serves the logo and the browser-tab icon.

Used by: app.py (registers it), routes_admin.py (Settings page), templates (base.html).
Logo order: 1) a logo uploaded in Admin > Settings  (<data folder>/branding/logo.*)
            2) the default file static/logo.png      (replace this file to change the default)
"""
import os

from flask import Blueprint, current_app, send_file

import config

bp = Blueprint("brand", __name__, url_prefix="/brand")


def custom_logo_path():
    for ext in sorted(config.LOGO_EXTENSIONS):
        path = os.path.join(config.BRAND_DIR, "logo." + ext)
        if os.path.exists(path):
            return path
    return None


def logo_version():
    """Changes when the logo changes, so browsers load the new picture."""
    path = custom_logo_path()
    return int(os.path.getmtime(path)) if path else 0


@bp.route("/logo")
def logo():
    path = custom_logo_path() or os.path.join(current_app.static_folder, "logo.png")
    return send_file(path, max_age=3600)


@bp.route("/icon")
def icon():
    path = custom_logo_path() or os.path.join(current_app.static_folder, "favicon.png")
    return send_file(path, max_age=3600)
