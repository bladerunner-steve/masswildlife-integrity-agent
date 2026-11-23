"""masswildlife.provenance_index writes: one row per receipt (steps 0-5) and per seal (step 6), inserted only
after the object is safely in the vault (store_and_index), plus the verifier's verdict (UPDATE only).

Plain INSERT (not upsert): a second row for the same (run_id, step) is an error, never a silent overwrite.
Untrusted convenience. The verifier never reads this table.
AI-assisted (Claude). Verified by: tests/test_index.py (SQL shape via a fake connection; optional live test
against the test env rows).
"""
from __future__ import annotations

from datetime import datetime

from mwia.common.timeutil import parse_utc
from mwia.vault.base import VaultBackend

from .db import GuardedConnection

SEAL_STEP = 6
STATUSES = ("unverified", "VERIFIED WITHIN SCOPE", "INSUFFICIENT EVIDENCE", "VERIFICATION FAILED")
CONFIGS = ("crypto", "crypto+policy", "crypto+policy+evidence")

INSERT_SQL = (
    "INSERT INTO provenance_index (run_id, step, env, step_type, module, agent_id, receipt_timestamp, "
    "receipt_hash, signature, notary_key_id, vault_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
UPDATE_SQL = (
    "UPDATE provenance_index SET verification_status = %s, verification_config = %s, "
    "verified_at = UTC_TIMESTAMP(6) WHERE run_id = %s"
)


def _naive_utc(ts: str) -> datetime:
    return parse_utc(ts).replace(tzinfo=None)


def row_for(env: str, obj: dict, vault_key: str) -> tuple:
    b = obj["body"]
    if "seal_hash" in obj:
        return (b["run_id"], SEAL_STEP, env, "seal", "notary", None, _naive_utc(b["timestamp"]), obj["seal_hash"],
                obj["signature"], b["notary_key_id"], vault_key)
    return (b["run_id"], b["step"], env, b["step_type"], b["module"], b["agent_id"], _naive_utc(b["timestamp"]),
            obj["receipt_hash"], obj["signature"], b["notary_key_id"], vault_key)


def index_object(db: GuardedConnection, env: str, obj: dict, vault_key: str) -> None:
    db.execute(INSERT_SQL, row_for(env, obj, vault_key))
    db.commit()


def store_and_index(vault: VaultBackend, db: GuardedConnection | None, env: str, key: str, obj: dict) -> None:
    """Write a receipt or seal to the vault first; index it only once the vault write succeeded."""
    vault.put_json(key, obj)
    if db is not None:
        index_object(db, env, obj, key)


def update_verification(db: GuardedConnection, run_id: str, status: str, config: str) -> int:
    if status not in STATUSES or config not in CONFIGS:
        raise ValueError("unknown verification status or config")
    cur = db.execute(UPDATE_SQL, (status, config, run_id))
    db.commit()
    return cur.rowcount
