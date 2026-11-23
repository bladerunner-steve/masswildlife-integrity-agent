"""Tests for the guarded DB connection and provenance index (mwia.index).

Unit tests use a fake connection. test_live_* runs only with MWIA_DB_TESTS=1: it connects as `claude`
with the real .env and writes env='test' rows to provenance_index. Those rows can't be deleted by `claude`;
an admin clears them with sql/admin/900_reset_test.sql. AI-assisted (Claude)."""
import os
import uuid
from pathlib import Path

import pytest

from mwia.index.db import GuardedConnection, SqlNotAllowed, classify
from mwia.index.provenance import INSERT_SQL, row_for, store_and_index, update_verification

from conftest import build_chain

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("sql,op", [
    ("SELECT id FROM inaturalist WHERE id = %s", "SELECT"),
    ("  select 1", "SELECT"),
    ("INSERT INTO t (a) VALUES (%s) ON DUPLICATE KEY UPDATE a = VALUES(a)", "INSERT"),
    ("UPDATE provenance_index SET verification_status = %s WHERE run_id = %s", "UPDATE"),
    ("SELECT created_at, updated_at FROM inaturalist", "SELECT"),   # 'created' is not the keyword CREATE
])
def test_allowed_sql(sql, op):
    assert classify(sql) == op


@pytest.mark.parametrize("sql", [
    "DELETE FROM inaturalist WHERE id = 1",
    "TRUNCATE TABLE inaturalist_test",
    "REPLACE INTO inaturalist (id) VALUES (1)",
    "DROP TABLE x", "ALTER TABLE x ADD c INT", "CREATE TABLE x (a INT)",
    "SELECT 1; DELETE FROM inaturalist",
    "SELECT 1 -- comment", "SELECT /* x */ 1",
    "UPDATE t SET a = 1 WHERE b IN (SELECT 1) OR 1=1; DROP TABLE t",
    "INSERT INTO t SELECT * FROM u WHERE x = REPLACE('a','b','c')",
    "GRANT ALL ON *.* TO claude", "LOAD DATA INFILE 'x' INTO TABLE t", "CALL p()",
    "SET SESSION TRANSACTION READ WRITE",
])
def test_forbidden_sql(sql):
    with pytest.raises(SqlNotAllowed):
        classify(sql)


def test_policy_allowed_set_is_enforced():
    with pytest.raises(SqlNotAllowed):
        classify("UPDATE t SET a = 1", allowed=("SELECT",))


class FakeCursor:
    rowcount = 6

    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def executemany(self, sql, seq):
        self.log.append((sql, list(seq)))


class FakeConn:
    def __init__(self):
        self.log, self.commits = [], 0

    def cursor(self):
        return FakeCursor(self.log)

    def commit(self):
        self.commits += 1


def test_guard_records_ops_and_blocks_before_db():
    fc = FakeConn()
    db = GuardedConnection(fc, "claude")
    db.execute("SELECT 1")
    db.executemany("INSERT INTO t (a) VALUES (%s) ON DUPLICATE KEY UPDATE a = VALUES(a)", [(1,), (2,)])
    with pytest.raises(SqlNotAllowed):
        db.execute("DELETE FROM t")
    assert db.ops_used == {"SELECT", "INSERT"}
    assert len(fc.log) == 2  # the DELETE never reached the connection


def test_rows_for_receipt_and_seal(notary):
    rs = build_chain(notary, notary.key_id)
    seal = notary.seal_run(rs[0]["body"]["run_id"])
    r = row_for("test", rs[3], "runs/k/3-filtering.json")
    assert r[1:5] == (3, "test", "filtering", "M3:filter") and r[7] == rs[3]["receipt_hash"]
    assert r[6].tzinfo is None
    s = row_for("test", seal, "runs/k/seal.json")
    assert s[1:6] == (6, "test", "seal", "notary", None) and s[7] == seal["seal_hash"]


def test_store_and_index_writes_vault_first(notary, vault):
    rs = build_chain(notary, notary.key_id, steps=[0])
    fc = FakeConn()
    store_and_index(vault, GuardedConnection(fc, "claude"), "test", "runs/d/r/0-plan.json", rs[0])
    assert vault.exists("runs/d/r/0-plan.json") and fc.log[0][0] == INSERT_SQL and fc.commits == 1
    fc2 = FakeConn()
    with pytest.raises(Exception):  # vault refuses the duplicate key, so nothing is indexed
        store_and_index(vault, GuardedConnection(fc2, "claude"), "test", "runs/d/r/0-plan.json", rs[0])
    assert fc2.log == []


def test_update_verification_validates():
    db = GuardedConnection(FakeConn(), "claude")
    assert update_verification(db, "r", "VERIFIED WITHIN SCOPE", "crypto+policy+evidence") == 6
    with pytest.raises(ValueError):
        update_verification(db, "r", "GREEN", "crypto")


@pytest.mark.skipif(os.environ.get("MWIA_DB_TESTS") != "1", reason="set MWIA_DB_TESTS=1 to run against MySQL")
def test_live_index_roundtrip(notary, vault):
    from mwia.index.db import connect
    db = connect(REPO / ".env")
    try:
        rs = build_chain(notary, notary.key_id, steps=[0])
        rid = rs[0]["body"]["run_id"]
        store_and_index(vault, db, "test", f"runs/live/{rid}/0-plan.json", rs[0])
        cur = db.execute("SELECT step, env, receipt_hash, verification_status FROM provenance_index WHERE run_id = %s",
                         (rid,))
        assert cur.fetchall() == ((0, "test", rs[0]["receipt_hash"], "unverified"),)
        assert update_verification(db, rid, "VERIFIED WITHIN SCOPE", "crypto") == 1
        with pytest.raises(Exception):  # second row for the same (run_id, step) is refused by the PK
            from mwia.index.provenance import index_object
            index_object(db, "test", rs[0], "dup")
        db.rollback()
        assert db.ops_used <= {"SELECT", "INSERT", "UPDATE"}
    finally:
        db.close()
