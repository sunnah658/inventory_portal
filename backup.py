"""
backup.py - make a safe copy of the database.

Used by: backup.sh (daily backup), routes_admin.py (automatic backup before a column
is erased for good).   Uses: config.py

Run by hand inside Docker:   docker compose exec portal python backup.py
It runs mysqldump (installed in the portal image, see the Dockerfile), so it is
safe while the portal is running: --single-transaction takes one consistent
snapshot of the InnoDB tables without locking them. The newest 30 backups are kept.
The password is passed through the MYSQL_PWD environment variable, so it never
shows in the process list.
"""
import glob
import os
import shutil
import subprocess
from datetime import datetime

import config

KEEP = 30


def make_backup(tag=""):
    """Create backups/portal_<tag><date>.sql and return its path."""
    mysqldump = shutil.which("mysqldump")
    if not mysqldump:
        raise RuntimeError("mysqldump is not installed in this container "
                           "(the Dockerfile installs default-mysql-client)")
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = os.path.join(config.BACKUP_DIR, f"portal_{tag}{stamp}.sql")
    env = dict(os.environ)
    env["MYSQL_PWD"] = config.DB_PASSWORD
    cmd = [mysqldump,
           f"--host={config.DB_HOST}", f"--port={config.DB_PORT}",
           f"--user={config.DB_USER}",
           "--single-transaction", "--quick",
           "--routines", "--triggers",
           config.DB_NAME]
    with open(target, "w", encoding="utf-8") as out:
        proc = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE,
                              env=env, text=True, timeout=600)
    if proc.returncode != 0:
        os.remove(target)
        raise RuntimeError(f"mysqldump failed: {proc.stderr.strip()}")
    for old in sorted(glob.glob(os.path.join(config.BACKUP_DIR, "portal_*.sql")))[:-KEEP]:
        os.remove(old)
    return target


if __name__ == "__main__":
    print("Backup saved:", make_backup())
