"""Database stores used by the agent modules, all via the guarded connection (SELECT/INSERT/UPDATE only).

ObservationStore: read existing rows (M3), idempotent upsert with INSERT ... AS new ON DUPLICATE KEY UPDATE
(MySQL 8.0.19+ row alias, server is 8.0.27), and readback after commit (M4). With PyMySQL's default flags
(no CLIENT.FOUND_ROWS, checked), affected rows are 1 = inserted, 2 = updated, 0 = unchanged.
RunStateStore: incremental windows in agent_run_state (INSERT at start, UPDATE at close; never DELETE).
Table names come only from a fixed allow-list, never from user input.
AI-assisted (Claude). Verified by: tests/test_pipeline.py (fake stores, same interface) and the live
Checkpoint 3 run against masswildlife.inaturalist_test.
"""
from __future__ import annotations

from datetime import datetime

from mwia.index.db import GuardedConnection

from .transform import COLUMNS, UPDATABLE

TABLES = {"inaturalist", "inaturalist_test"}
CHUNK = 500


class ObservationStore:
    def __init__(self, db: GuardedConnection, table: str):
        if table not in TABLES:
            raise ValueError(f"table {table!r} is not an allowed target")
        self.db, self.table = db, table
        cols = ", ".join(COLUMNS)
        ph = ", ".join(["%s"] * len(COLUMNS))
        upd = ", ".join(f"{c} = new.{c}" for c in UPDATABLE)
        self.upsert_sql = f"INSERT INTO {table} ({cols}) VALUES ({ph}) AS new ON DUPLICATE KEY UPDATE {upd}"

    @property
    def user(self) -> str:
        return self.db.user

    @property
    def ops_used(self) -> set[str]:
        return self.db.ops_used

    def fetch(self, ids: list[int]) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for i in range(0, len(ids), CHUNK):
            chunk = ids[i:i + CHUNK]
            if not chunk:
                continue
            sql = f"SELECT {', '.join(COLUMNS)} FROM {self.table} WHERE id IN ({', '.join(['%s'] * len(chunk))})"
            for r in self.db.execute(sql, chunk).fetchall():
                out[r[0]] = dict(zip(COLUMNS, r))
        return out

    def upsert(self, rows: list[dict]) -> list[int]:
        """One transaction; returns affected-row counts per row (1 insert, 2 update, 0 unchanged)."""
        results = []
        self.db.begin()
        try:
            for row in rows:
                results.append(self.db.execute(self.upsert_sql, [row[c] for c in COLUMNS]).rowcount)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return results

    def readback(self, ids: list[int]) -> list[dict]:
        rows = self.fetch(sorted(ids))
        return [rows[i] for i in sorted(rows)]


class RunStateStore:
    def __init__(self, db: GuardedConnection):
        self.db = db

    def last_success_end(self, env: str) -> datetime | None:
        cur = self.db.execute("SELECT window_end FROM agent_run_state WHERE env = %s AND status = %s AND dry_run = 0 "
                              "ORDER BY window_end DESC LIMIT 1", (env, "success"))
        r = cur.fetchone()
        return r[0] if r else None

    def start(self, run_id: str, env: str, dry_run: bool, start: datetime, end: datetime, gap: int | None,
              started_at: datetime, prev_seal: str) -> None:
        self.db.execute("INSERT INTO agent_run_state (run_id, env, dry_run, window_start, window_end, status, "
                        "gap_seconds, started_at, prev_seal_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (run_id, env, int(dry_run), start, end, "running", gap, started_at, prev_seal))
        self.db.commit()

    def finish(self, run_id: str, status: str, finished_at: datetime, seal_hash: str | None) -> None:
        self.db.execute("UPDATE agent_run_state SET status = %s, finished_at = %s, seal_hash = %s WHERE run_id = %s",
                        (status, finished_at, seal_hash, run_id))
        self.db.commit()
