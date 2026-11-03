"""
reset_admin.py - emergency tool: give a user a new temporary password (default: admin).

Use it when the only admin forgot the password. It also re-activates the account and
forces a password change at the next login.

    docker compose exec portal python reset_admin.py            (resets "admin")
    docker compose exec portal python reset_admin.py karim      (resets user "karim")
"""
import sys

from werkzeug.security import generate_password_hash

import models
from utils import generate_password

username = sys.argv[1] if len(sys.argv) > 1 else "admin"
conn = models.connect()
if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is None:
    print(f"No user named '{username}'.")
    sys.exit(1)
password = generate_password()
conn.execute("UPDATE users SET password_hash=?, must_change_password=1, is_active=1 WHERE username=?",
             (generate_password_hash(password), username))
conn.commit()
conn.close()
print(f"New temporary password for {username}: {password}")
print("Log in with it; you will be asked to choose a new password.")
