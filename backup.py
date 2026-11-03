"""
backup.py - make a safe copy of the database.

Used by: backup.sh (daily backup), routes_admin.py (automatic backup before a column
is erased for good).   Uses: config.py

Run by hand inside Docker:   docker compose exec portal python backup.py
It uses SQLite's own backup function, so it is safe while the portal is running and
it includes the latest saved entries. The newest 30 backups are kept.
"""
import glob
import os
import sqlite3
from datetime import datetime

import config

KEEP = 30


def make_backup(tag=""):
    """Create backups/portal_<tag><date>.db and return its path."""
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = os.path.join(config.BACKUP_DIR, f"portal_{tag}{stamp}.db")
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    for old in sorted(glob.glob(os.path.join(config.BACKUP_DIR, "portal_*.db")))[:-KEEP]:
        os.remove(old)
    return target


if __name__ == "__main__":
    print("Backup saved:", make_backup())
