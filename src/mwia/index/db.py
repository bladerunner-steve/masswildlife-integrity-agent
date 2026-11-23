"""Guarded MySQL connection for the agent account `claude`.

Every statement must start with SELECT, INSERT or UPDATE, and must not contain DELETE, TRUNCATE, DROP,
ALTER, CREATE, REPLACE, GRANT, REVOKE, RENAME or LOAD as a keyword. Values are always passed as parameters
(%s), never formatted into the SQL. The guard records which operation types were used (for PR4) and enforces
the policy's allowed set before MySQL sees the statement. The MySQL grant is the second, independent line
of defence.
Credentials are read from .env with dotenv_values (only MYSQL_*), so the agent process never loads
NOTARY_KEY_PASSPHRASE into its environment. MYSQL_PASSWORD is never printed or logged.
AI-assisted (Claude). Verified by: tests/test_index.py (guard unit tests + optional live DB test).
"""
from __future__ import annotations

import re
from pathlib import Path

ALLOWED = ("SELECT", "INSERT", "UPDATE")
FORBIDDEN = re.compile(r"\b(DELETE|TRUNCATE|DROP|ALTER|CREATE|REPLACE|GRANT|REVOKE|RENAME|LOAD|HANDLER|CALL)\b",
                       re.IGNORECASE)


class SqlNotAllowed(Exception):
    pass


def classify(sql: str, allowed: tuple[str, ...] = ALLOWED) -> str:
    """Return the operation type of sql, or raise SqlNotAllowed."""
    stripped = sql.strip()
    if ";" in stripped.rstrip(";"):
        raise SqlNotAllowed("multiple statements are not allowed")
    if "--" in stripped or "/*" in stripped or "#" in stripped:
        raise SqlNotAllowed("SQL comments are not allowed")
    m = re.match(r"^\(?\s*([A-Za-z]+)", stripped)
    op = m.group(1).upper() if m else ""
    if op not in allowed:
        raise SqlNotAllowed(f"operation {op or '?'} is not in the allowed set {list(allowed)}")
    bad = FORBIDDEN.search(stripped)
    if bad:
        raise SqlNotAllowed(f"keyword {bad.group(1).upper()} is not allowed")
    if "ON DUPLICATE KEY UPDATE" not in stripped.upper() and op == "INSERT" and "UPDATE" in stripped.upper():
        raise SqlNotAllowed("UPDATE inside INSERT is only allowed as ON DUPLICATE KEY UPDATE")
    return op


class GuardedConnection:
    def __init__(self, conn, user: str, allowed: tuple[str, ...] = ALLOWED):
        self._conn = conn
        self.user = user
        self.allowed = allowed
        self.ops_used: set[str] = set()

    def execute(self, sql: str, params=None):
        op = classify(sql, self.allowed)
        cur = self._conn.cursor()
        cur.execute(sql, params)
        self.ops_used.add(op)
        return cur

    def executemany(self, sql: str, seq_params):
        op = classify(sql, self.allowed)
        cur = self._conn.cursor()
        cur.executemany(sql, seq_params)
        self.ops_used.add(op)
        return cur

    def begin(self) -> None:
        self._conn.begin()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def connect(env_file: Path, allowed: tuple[str, ...] = ALLOWED) -> GuardedConnection:
    import pymysql
    from dotenv import dotenv_values

    cfg = {k: v for k, v in dotenv_values(env_file).items() if k.startswith("MYSQL_")}
    missing = [k for k in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE") if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"missing in {env_file.name}: {', '.join(missing)}")
    conn = pymysql.connect(host=cfg["MYSQL_HOST"], port=int(cfg.get("MYSQL_PORT") or 3306), user=cfg["MYSQL_USER"],
                           password=cfg["MYSQL_PASSWORD"], database=cfg["MYSQL_DATABASE"], charset="utf8mb4",
                           autocommit=False)
    return GuardedConnection(conn, cfg["MYSQL_USER"], allowed)
