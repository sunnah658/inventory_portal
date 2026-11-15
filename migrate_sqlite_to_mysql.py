#!/usr/bin/env python3
"""migrate_sqlite_to_mysql.py - move the portal's data from SQLite to MySQL.

This is the one-time move from the old database (one SQLite file,
portal.db) to the new MySQL database (build 67). It copies every row of
every table, keeping the same IDs, so invoice numbers, record links,
public QR codes and approval chains all keep working exactly as before.

How to run it (on the server, after the new portal code is in place but
BEFORE the portal is started on MySQL):

    # 1. Stop the portal (so nobody changes the SQLite file while it copies)
    docker compose stop portal

    # 2. Copy the live SQLite file out of the volume (or point at it directly)
    docker compose cp portal:/data/portal.db /tmp/portal.db

    # 3. Start the database container (it creates the empty "portal" database)
    docker compose up -d db

    # 4. Run the migration. It reads the SQLite file and writes into MySQL.
    #    The MySQL connection comes from the environment (DB_HOST, DB_PORT,
    #    DB_USER, DB_PASSWORD, DB_NAME) — the same variables the portal uses.
    docker compose run --rm portal python migrate_sqlite_to_mysql.py /tmp/portal.db

    # 5. Start the portal on MySQL
    docker compose up -d

If the MySQL database already has rows, the script refuses to run (so it
can never copy the same data twice). Pass --replace to empty the MySQL
tables first and copy again. The old SQLite file is never changed.

What it does, in order:
  1. Creates the MySQL database and the empty tables (the portal's SCHEMA).
  2. Copies every table, parents before children, keeping every ID.
     The `settings.key` column is renamed `setting_key` (KEY is a
     reserved word in MySQL), and generated columns (the name_live /
     name_dept / name_user helpers behind the unique indexes) are skipped
     — MySQL computes them itself.
  3. Resets each table's next auto-number to one past its highest ID.
  4. Runs the portal's own init_db(), which applies the startup
     backfills (Custom Application kinds, the Sales Pipeline tab) to the
     migrated data, and verifies the portal boots on it.
  5. Checks every table's row count against the SQLite file and reports
     any mismatch. It exits non-zero if any table does not match.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dbapi
import models


def _sqlite_tables(src):
    return [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name")]


def _mysql_columns(dst, table):
    """(column, type, is_generated) for a MySQL table, in order."""
    rows = dst.execute(
        "SELECT COLUMN_NAME, DATA_TYPE, EXTRA FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=? ORDER BY ORDINAL_POSITION",
        (table,)).fetchall()
    return [(r[0], r[1], "GENERATED" in (r[2] or "")) for r in rows]


def _copy_order(src, tables):
    """Parents before children, from the SQLite foreign keys (Kahn's
    algorithm). A table that only references itself adds no constraint."""
    deps = {}
    for t in tables:
        refs = {r[2] for r in src.execute(f"PRAGMA foreign_key_list({t})")}
        deps[t] = {r for r in refs if r in tables and r != t}
    order, done = [], set()
    while len(order) < len(tables):
        ready = sorted(t for t in tables if t not in done and deps[t] <= done)
        if not ready:   # a cycle (should not happen): take the rest in name order
            ready = sorted(t for t in tables if t not in done)
        for t in ready:
            order.append(t)
            done.add(t)
    return order


def _target_has_rows(dst, tables):
    for t in tables:
        if dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]:
            return t
    return None


def migrate(sqlite_path, replace=False):
    if not os.path.exists(sqlite_path):
        print(f"ERROR: no SQLite file at {sqlite_path}")
        return 2
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    dbapi.ensure_database()
    dst = models.connect()
    # The empty tables, from the portal's own SCHEMA (no seed admin yet).
    dst.executescript(models.SCHEMA)
    dst.commit()

    src_tables = _sqlite_tables(src)
    dst_tables = [r[0] for r in dst.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()")]
    tables = [t for t in _copy_order(src, src_tables) if t in dst_tables]
    skipped = [t for t in src_tables if t not in dst_tables]
    if skipped:
        print(f"Skipping tables with no MySQL equivalent: {', '.join(skipped)}")

    if not replace:
        busy = _target_has_rows(dst, tables)
        if busy:
            print(f"ERROR: the MySQL database already has rows in {busy}. "
                  "Refusing to copy over them (run again with --replace to "
                  "empty the MySQL tables first).")
            return 2
    if replace:
        dst.execute("SET FOREIGN_KEY_CHECKS=0")
        for t in tables:
            dst.execute(f"TRUNCATE TABLE {t}")
        dst.execute("SET FOREIGN_KEY_CHECKS=1")
        dst.commit()
        print("Emptied the MySQL tables (--replace).")

    # settings.key -> setting_key (KEY is a reserved word in MySQL).
    # Map: MySQL column -> SQLite column.
    rename = {"settings": {"setting_key": "key"}}

    dst.execute("SET FOREIGN_KEY_CHECKS=0")
    copied = {}
    try:
        for t in tables:
            cols = _mysql_columns(dst, t)
            # Skip generated columns (MySQL computes them); map renamed ones.
            pairs = []   # (mysql column, sqlite column)
            for (c, _ty, gen) in cols:
                if gen:
                    continue
                s = rename.get(t, {}).get(c, c)
                pairs.append((c, s))
            have = [r[1] for r in src.execute(f"PRAGMA table_info({t})")]
            pairs = [(c, s) for (c, s) in pairs if s in have]
            if not pairs:
                print(f"  {t}: no shared columns, skipped")
                continue
            # An empty string is not a valid DATETIME/DATE in MySQL.
            temporal = {c for (c, _s) in pairs
                        if _mysql_col_is_temporal(dst, t, c)}
            rows = src.execute(
                "SELECT " + ", ".join(f'"{s}"' for _c, s in pairs) + f" FROM {t}").fetchall()
            n = 0
            for r in rows:
                vals = []
                for (c, s) in pairs:
                    v = r[s]
                    if v == "" and c in temporal:
                        v = None
                    vals.append(v)
                dst.execute(
                    f"INSERT INTO {t} (" + ", ".join(c for c, _s in pairs) + ") VALUES (" +
                    ", ".join("?" * len(pairs)) + ")",
                    tuple(vals))
                n += 1
            copied[t] = n
            print(f"  {t}: {n} rows")
        dst.execute("SET FOREIGN_KEY_CHECKS=1")
        dst.commit()
    except Exception:
        dst.rollback()
        raise

    # Next auto-number = one past the highest ID in each table.
    for t in tables:
        row = dst.execute(
            "SELECT AUTO_INCREMENT FROM information_schema.tables "
            "WHERE table_schema=DATABASE() AND table_name=?", (t,)).fetchone()
        if row and row[0] is not None:
            mx = dst.execute(f"SELECT MAX(id) FROM {t}").fetchone()[0]
            if mx is not None:
                dst.execute(f"ALTER TABLE {t} AUTO_INCREMENT = {mx + 1}")
    dst.commit()

    # Verify: every table must hold exactly as many rows as the SQLite file.
    # (Checked BEFORE init_db(): its backfills legitimately add rows, e.g.
    # a Custom Application kind per department.)
    bad = []
    for t in tables:
        want = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        got = dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        if want != got:
            bad.append((t, want, got))
    total = sum(copied.values())
    if bad:
        for t, want, got in bad:
            print(f"ERROR: {t}: SQLite has {want} rows, MySQL has {got}")
        return 1
    print(f"OK: {total} rows copied into {len(tables)} tables, counts match.")

    # The portal's own startup (backfills + a boot check) on the migrated data.
    models.init_db()
    print("init_db() ran on the migrated data (backfills applied, portal boots).")
    return 0


def _mysql_col_is_temporal(dst, table, column):
    row = dst.execute(
        "SELECT DATA_TYPE FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=? AND column_name=?",
        (table, column)).fetchone()
    return row is not None and row[0] in ("datetime", "date", "timestamp", "time")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    replace = "--replace" in sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        print("usage: python migrate_sqlite_to_mysql.py [--replace] /path/to/portal.db")
        sys.exit(2)
    sys.exit(migrate(args[0], replace=replace))
