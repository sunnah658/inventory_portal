"""dbapi.py - the portal's database layer (MySQL).

The portal's code was written against Python's sqlite3 module: ``?``
placeholders, ``sqlite3.Row`` (a row that answers both ``row["name"]``
and ``row[0]``), ``Connection.execute`` returning a cursor, and SQLite
date functions (``datetime('now','localtime')``). This module keeps
that exact surface and runs it on MySQL through PyMySQL, so the rest
of the portal does not change:

* ``connect()`` returns a ``Connection`` whose ``execute(sql, params)``
  returns a ``Cursor`` with ``fetchone`` / ``fetchall`` / ``fetchmany`` /
  ``lastrowid`` / ``rowcount`` / iteration, exactly like sqlite3.
* ``Row`` is a dict (``row["name"]``, ``row.get("name")``) that also
  answers ``row[0]`` (first column) and iterates over its VALUES, like
  ``sqlite3.Row`` — so ``for (d,) in db.execute(...)`` and
  ``[r[0] for r in db.execute(...)]`` keep working.
* Dates and datetimes come back as the strings the portal expects
  (``'2026-11-15'`` / ``'2026-11-15 12:00:00'``), because the portal
  parses them with ``strptime`` and slices them (``[:10]``).
* ``translate_sql`` rewrites the SQLite dialect the portal uses into
  MySQL: ``?`` -> ``%s`` (only outside string literals), ``INSERT OR
  IGNORE`` -> ``INSERT IGNORE``, ``ON CONFLICT(...) DO UPDATE SET ...
  = excluded.x`` -> ``ON DUPLICATE KEY UPDATE ... = VALUES(x)``,
  ``datetime('now','localtime')`` -> ``NOW()`` (and the fixed
  ``-N days`` / ``-N minutes`` offsets -> ``DATE_SUB``),
  ``date('now','localtime')`` -> ``CURDATE()``, and ``COLLATE NOCASE``
  is dropped (MySQL's default collation is already case-insensitive).
  ``ESCAPE '\'`` (one backslash, SQLite's form) -> ``ESCAPE '\\'``
  (MySQL needs two backslashes for the same one-backslash escape
  character; one backslash is an escaped quote there and breaks the
  query with error 1064).
  A literal ``%`` in the SQL is doubled to ``%%`` when parameters are
  passed, so ``LIKE '%sales%'`` does not break PyMySQL's ``%``
  formatting. The one expression that cannot be translated is the
  parameterised offset ``datetime('now','localtime',?)`` (the parameter
  is a string like ``'-7 days'``); those twelve call sites were
  rewritten by hand to ``DATE_SUB(NOW(), INTERVAL ? DAY/MINUTE)``.
"""
import re
from datetime import date, datetime

import pymysql

import config

# The exceptions the portal catches (they used to be sqlite3's).
IntegrityError = pymysql.err.IntegrityError
OperationalError = pymysql.err.OperationalError
DatabaseError = pymysql.err.DatabaseError
Error = pymysql.err.Error


# ---------------------------------------------------------------------------
# SQL translation (SQLite dialect -> MySQL)
# ---------------------------------------------------------------------------

def _re(pattern, repl, sql):
    return re.sub(pattern, repl, sql, flags=re.IGNORECASE)


def _translate_functions(sql):
    """Rewrite SQLite-only functions and clauses to MySQL. Runs before
    the placeholder pass, so it never sees a ``%s`` it did not make."""
    # INSERT OR IGNORE / INSERT OR REPLACE (SQLite) -> MySQL's forms.
    sql = _re(r"\bINSERT\s+OR\s+IGNORE\b", "INSERT IGNORE", sql)
    sql = _re(r"\bINSERT\s+OR\s+REPLACE\b", "REPLACE", sql)
    # ON CONFLICT(key) DO UPDATE SET x=excluded.x -> ON DUPLICATE KEY UPDATE x=VALUES(x).
    sql = _re(r"\bON\s+CONFLICT\s*\([^)]*\)\s*DO\s+UPDATE\s+SET\b",
              "ON DUPLICATE KEY UPDATE", sql)
    sql = _re(r"\bexcluded\.(\w+)", r"VALUES(\1)", sql)
    # datetime('now','localtime','-N days'/'-N minutes') -> DATE_SUB(NOW(), ...).
    sql = _re(r"""datetime\(\s*'now'\s*,\s*'localtime'\s*,\s*'-\s*(\d+)\s+days'\s*\)""",
              r"DATE_SUB(NOW(), INTERVAL \1 DAY)", sql)
    sql = _re(r"""datetime\(\s*'now'\s*,\s*'localtime'\s*,\s*'-\s*(\d+)\s+minutes'\s*\)""",
              r"DATE_SUB(NOW(), INTERVAL \1 MINUTE)", sql)
    # datetime('now','localtime') -> NOW(); datetime('now') -> UTC_TIMESTAMP().
    sql = _re(r"""datetime\(\s*'now'\s*,\s*'localtime'\s*\)""", "NOW()", sql)
    sql = _re(r"""datetime\(\s*'now'\s*\)""", "UTC_TIMESTAMP()", sql)
    # date('now','localtime','-N days') -> DATE_SUB(CURDATE(), ...).
    sql = _re(r"""date\(\s*'now'\s*,\s*'localtime'\s*,\s*'-\s*(\d+)\s+days'\s*\)""",
              r"DATE_SUB(CURDATE(), INTERVAL \1 DAY)", sql)
    sql = _re(r"""date\(\s*'now'\s*,\s*'localtime'\s*\)""", "CURDATE()", sql)
    sql = _re(r"""date\(\s*'now'\s*\)""", "UTC_DATE()", sql)
    # COLLATE NOCASE is SQLite-only; MySQL's default collation is already
    # case-insensitive, so it is simply dropped.
    sql = _re(r"\s+COLLATE\s+NOCASE\b", "", sql)
    # ESCAPE '\' (one backslash) is SQLite's way of saying "backslash is
    # the LIKE escape character" — in SQLite a backslash inside a string
    # is literal. In MySQL, '\' is an escaped quote, which leaves the
    # string unterminated (error 1064); MySQL needs two backslashes
    # (ESCAPE '\\') for the same one-backslash escape character.
    sql = re.sub(r"ESCAPE\s+'\\'", lambda m: "ESCAPE '\\\\'", sql, flags=re.IGNORECASE)
    return sql


def _translate_placeholders(sql, has_params):
    """``?`` -> ``%s`` outside string literals, and a literal ``%`` ->
    ``%%`` when parameters are passed (PyMySQL formats the query with
    Python's ``%`` operator, so an unescaped ``%`` would be read as a
    format specifier). A ``?`` inside a quoted string is a literal
    question mark and is left alone."""
    out = []
    i, n = 0, len(sql)
    in_str = False
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":   # '' = an escaped quote
                    out.append("''")
                    i += 2
                    continue
                in_str = False
                out.append(ch)
                i += 1
                continue
            if ch == "%" and has_params:
                out.append("%%")
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == "'":
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "?":
            out.append("%s")
            i += 1
            continue
        if ch == "%" and has_params:
            out.append("%%")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def translate_sql(sql, has_params=False):
    """Translate one SQLite-flavoured statement to MySQL."""
    return _translate_placeholders(_translate_functions(sql), has_params)


def _split_script(script):
    """Split a multi-statement script (the SCHEMA) into single
    statements, respecting quoted strings and -- / /* */ comments."""
    stmts, buf = [], []
    i, n = 0, len(script)
    in_str = in_line = in_block = False
    while i < n:
        ch, nxt = script[i], script[i + 1] if i + 1 < n else ""
        if in_line:
            buf.append(ch)
            if ch == "\n":
                in_line = False
            i += 1
            continue
        if in_block:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 2
                in_block = False
                continue
            i += 1
            continue
        if in_str:
            buf.append(ch)
            if ch == "'":
                if nxt == "'":
                    buf.append(nxt)
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "-" and nxt == "-" and (i + 2 >= n or script[i + 2] in " \t"):
            in_line = True
            buf.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            buf.append(ch)
            i += 1
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


# ---------------------------------------------------------------------------
# Rows, cursors, connections
# ---------------------------------------------------------------------------

def _convert_value(value):
    """A DATETIME / DATE from MySQL comes back as a datetime object;
    the portal expects the string it used to get from SQLite."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return value


class Row(dict):
    """One result row: a dict (``row["name"]``) that also answers
    ``row[0]`` (first column) and iterates over its VALUES, like
    ``sqlite3.Row``."""

    def __init__(self, columns, values):
        super().__init__(zip(columns, [_convert_value(v) for v in values]))
        self._columns = list(columns)

    def __getitem__(self, key):
        if isinstance(key, int):
            return super().__getitem__(self._columns[key])
        return super().__getitem__(key)

    def __contains__(self, key):
        if isinstance(key, int):
            return -len(self._columns) <= key < len(self._columns)
        return super().__contains__(key)

    def __iter__(self):
        # sqlite3.Row iterates over values, not keys.
        return (self[c] for c in self._columns)


class Cursor:
    """Wraps a PyMySQL cursor; fetch methods return Row objects."""

    def __init__(self, raw):
        self._cur = raw

    def __del__(self):
        try:
            self._cur.close()
        except Exception:
            pass

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def _columns(self):
        return [d[0] for d in self._cur.description] if self._cur.description else []

    def _wrap(self, rows):
        cols = self._columns()
        return [Row(cols, r) for r in rows]

    def fetchone(self):
        if self._cur.description is None:
            return None
        row = self._cur.fetchone()
        if row is None:
            return None
        return Row(self._columns(), row)

    def fetchall(self):
        if self._cur.description is None:
            return []
        return self._wrap(self._cur.fetchall())

    def fetchmany(self, size=None):
        if self._cur.description is None:
            return []
        return self._wrap(self._cur.fetchmany(size))

    def __iter__(self):
        if self._cur.description is None:
            return
        cols = self._columns()
        for row in self._cur:
            yield Row(cols, row)

    def close(self):
        self._cur.close()


class Connection:
    """Wraps a PyMySQL connection; ``execute`` returns a Cursor, like
    sqlite3's ``Connection.execute``."""

    def __init__(self, raw):
        self._conn = raw

    def execute(self, sql, params=None):
        translated = translate_sql(sql, params is not None)
        cur = self._conn.cursor()
        try:
            cur.execute(translated, params)
        except Exception:
            cur.close()
            raise
        return Cursor(cur)

    def executemany(self, sql, seq):
        translated = translate_sql(sql, True)
        cur = self._conn.cursor()
        try:
            cur.executemany(translated, seq)
        except Exception:
            cur.close()
            raise
        return Cursor(cur)

    def executescript(self, sql):
        for stmt in _split_script(sql):
            self.execute(stmt)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


# ---------------------------------------------------------------------------
# Connecting
# ---------------------------------------------------------------------------

def _db_name_ok(name):
    return bool(re.match(r"^[A-Za-z0-9_]+$", name or ""))


def ensure_database():
    """Create the portal database if it does not exist yet (first start)."""
    if not _db_name_ok(config.DB_NAME):
        raise ValueError(f"bad database name: {config.DB_NAME!r}")
    raw = pymysql.connect(host=config.DB_HOST, port=config.DB_PORT,
                          user=config.DB_USER, password=config.DB_PASSWORD,
                          charset="utf8mb4", connect_timeout=5)
    try:
        with raw.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{config.DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        raw.commit()
    finally:
        raw.close()


def connect():
    """Open a connection to the portal database."""
    raw = pymysql.connect(host=config.DB_HOST, port=config.DB_PORT,
                          user=config.DB_USER, password=config.DB_PASSWORD,
                          database=config.DB_NAME, charset="utf8mb4",
                          connect_timeout=5)
    return Connection(raw)
