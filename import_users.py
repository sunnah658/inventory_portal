"""
import_users.py - create many users from a CSV file.

Used by: routes_admin.py (Admin > Import users). Can also be run by hand.
Uses:    core.py, templates_data.py, utils.py

CSV columns (first row is the header):  full_name, username, department, role, password
`role` and `password` are optional. An empty password = a random temporary one.
A department that does not exist yet is created; if its name matches a starter
template (for example "IT" or "Accounts") it also gets that template's columns.

Command line:  docker compose exec portal python import_users.py /data/users.csv
"""
import csv
import io
import sys

from werkzeug.security import generate_password_hash

from core import create_department
from security import password_problem
from templates_data import match_template
from utils import generate_password

MAX_ROWS = 2000


def import_users(db, text):
    """Returns (created, skipped). created = list of dicts, skipped = list of messages."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["The file is empty."]
    reader.fieldnames = [(h or "").strip().lower().replace(" ", "_") for h in reader.fieldnames]
    if not {"full_name", "username", "department"}.issubset(reader.fieldnames):
        return [], ["The first row must contain: full_name, username, department "
                    "(role and password are optional)."]

    created, skipped = [], []
    for number, row in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            skipped.append(f"Stopped at {MAX_ROWS} rows.")
            break
        full_name = (row.get("full_name") or "").strip()
        username = (row.get("username") or "").strip()
        dept_name = (row.get("department") or "").strip()
        role = (row.get("role") or "user").strip().lower() or "user"
        password = (row.get("password") or "").strip()

        if not full_name and not username and not dept_name:
            continue                                      # blank line
        if not (full_name and username and dept_name):
            skipped.append(f"Line {number}: full_name, username and department are required.")
            continue
        if role not in ("user", "admin"):
            skipped.append(f"Line {number}: role must be user or admin.")
            continue
        if password and password_problem(password, username):
            skipped.append(f"Line {number}: {password_problem(password, username)}")
            continue
        if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            skipped.append(f"Line {number}: username '{username}' already exists.")
            continue

        dept = db.execute("SELECT id FROM departments WHERE name = ?", (dept_name,)).fetchone()
        dept_id = dept["id"] if dept else create_department(db, dept_name, match_template(dept_name))
        password = password or generate_password()
        db.execute("INSERT INTO users(full_name,username,password_hash,department_id,role,"
                   "must_change_password) VALUES (?,?,?,?,?,1)",
                   (full_name, username, generate_password_hash(password), dept_id, role))
        created.append({"full_name": full_name, "username": username,
                        "department": dept_name, "role": role, "password": password})
    return created, skipped


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Use: python import_users.py users.csv")
        sys.exit(1)
    import models
    models.init_db()
    conn = models.connect()
    with open(sys.argv[1], "r", encoding="utf-8-sig", newline="") as fh:
        made, skip = import_users(conn, fh.read())
    conn.commit()
    conn.close()
    print(f"Created {len(made)} users.")
    for item in made:
        print(f"  {item['username']}  temporary password: {item['password']}")
    for item in skip:
        print("  skipped -", item)
