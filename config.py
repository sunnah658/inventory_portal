"""
config.py - all portal settings in one place.

Most people only need the .env file (port, time zone). Change values here only if
you need something special. Almost every other file imports this one.
"""
import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- Where data is stored -------------------------------------------------
# In Docker, PORTAL_DATA=/data (a persistent Docker volume). Without Docker the
# data folder is the project folder. Uploads, branding and backups still live
# here as files; the database itself lives in MySQL (see below).
DATA_DIR = os.environ.get("PORTAL_DATA", BASE_DIR)
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")      # record attachments
BRAND_DIR = os.path.join(DATA_DIR, "branding")      # logo uploaded from Admin > Settings
BACKUP_DIR = os.path.join(DATA_DIR, "backups")      # database backups (.sql files)
for _folder in (DATA_DIR, UPLOAD_DIR, BRAND_DIR, BACKUP_DIR):
    os.makedirs(_folder, exist_ok=True)

# ---- The database (MySQL, since build 67) ----------------------------------
# The portal talks to a MySQL server (the "db" service in docker-compose.yml,
# or any MySQL 8.0 / MariaDB 10.6+ server). The settings come from the
# environment; docker-compose sets them from the .env file, falling back to
# the defaults below. Change the password by setting MYSQL_PASSWORD (and
# MYSQL_ROOT_PASSWORD for the database container) in your live .env BEFORE
# the first start — the database user is created with that password on
# first start, and changing it later does not change the user's password.
# The database data itself lives in the "mysql_data" Docker volume
# (mounted at /var/lib/mysql in the db container), so it survives a
# container rebuild or restart. NEVER run "docker compose down -v": it
# deletes that volume and the database with it.
DB_HOST = os.environ.get("DB_HOST", "db")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "portal")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "portal-change-me")
DB_NAME = os.environ.get("DB_NAME", "portal")

# ---- First admin account (created only once, on the very first start) -----
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "ChangeMe@123"      # must be changed at first login
DEFAULT_ADMIN_NAME = "Portal Admin"
DEFAULT_DEPARTMENT = "IT"
DEFAULT_COMPANY_NAME = "HRC Technologies Limited"   # can be changed in Admin > Settings
DEFAULT_COMPANY_ADDRESS = "Level 5, Motijheel C/A, Dhaka-1000 · +880 2 9555 0100"  # top of invoice PDFs; no email is ever shown there

# ---- Login and sessions ----------------------------------------------------
SESSION_HOURS = 8                                    # absolute limit: logout after this time
IDLE_MINUTES = 30                                    # logout after this many minutes without activity
HTTPS_ONLY = os.environ.get("PORTAL_HTTPS") == "1"   # 1 only if served over HTTPS
BEHIND_PROXY = os.environ.get("PORTAL_BEHIND_PROXY") == "1"   # 1 when the Caddy HTTPS proxy is used
MAX_FAILED = 5                                       # wrong passwords for one username before lock
LOCK_MINUTES = 5                                     # how long that lock lasts
IP_MAX_FAILED = 20                                   # wrong passwords from one computer (any usernames)
IP_LOCK_MINUTES = 10                                 # before that computer is blocked for this long
REAUTH_SECONDS = 300                                 # after typing the password for a dangerous action,
                                                     # no need to type it again for this long

# ---- Lists, recycle bin, logs ---------------------------------------------
PER_PAGE = 50              # rows per page in record lists
BIN_DAYS = 30              # deleted records are erased for good after this many days
ACTIVITY_KEEP_DAYS = 730   # old activity log lines are removed (history is never removed)
REMINDER_DAYS = 30         # "expiring soon" window for reminders
REMINDER_HOUR = min(max(int(os.environ.get("REMINDER_HOUR") or 7), 0), 23)   # reminder notifications go out from this hour (server time, TZ in .env)
WARN_DAY_CHOICES = (1, 3, 7)    # what a person may choose as "warn me N days ahead"

# ---- Attachments -----------------------------------------------------------
MAX_UPLOAD_MB = 25         # server-wide limit per file (admin sets a lower one per department)
MAX_REQUEST_MB = 100       # limit for one upload request (several files)
ALLOWED_EXTENSIONS = {     # anything else (exe, scripts, ...) is refused
    "pdf", "jpg", "jpeg", "png", "gif", "webp", "txt", "csv",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx",
}
LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


# ---- Public QR links ---------------------------------------------------------
PUBLIC_RATE_PER_MIN = 60   # requests per minute from one computer to public pages

# ---- Virus scanning of attachments (ClamAV) -----------------------------------
# Set CLAMAV_HOST (for example "clamav") to switch scanning on. Empty = scanning off.
CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "")
CLAMAV_PORT = int(os.environ.get("CLAMAV_PORT", "3310"))


def get_secret_key():
    """Create a random secret key once and keep it in <data folder>/secret.key."""
    path = os.path.join(DATA_DIR, "secret.key")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    return key
