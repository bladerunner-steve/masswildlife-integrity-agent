"""M4 database update -> PR4. Upserts the write set into the target table in one transaction, then reads
back every accepted row after commit.

Records: DB user, target table, SQL operation types actually used (from the guarded connection), dry-run
flag, planned versus actual inserted/updated/skipped, whether the transaction committed, and the readback.
out_hash = SHA-256 of the readback evidence object. Dry run: the guard allows only SELECT, nothing is
written, and every accepted row counts as skipped.
policy_decision is "pass" only if the user is the policy's DB user, the table is the policy's target (or
test target), and the operations used are within allowed_operations.
AI-assisted (Claude). Verified by: tests/test_pipeline.py (write, idempotent re-run, dry run) and the live
Checkpoint 3 run.
"""
from __future__ import annotations

from mwia.common.canonical import hash_obj

from .emit import RunContext
from .transform import COLUMNS

MODULE = "M4:db"
RULES = ["db.user", "db.target", "db.operations"]


def run(ctx: RunContext, m3: dict, store, table: str) -> dict:
    pol = ctx.cfg.policy["database"]
    planned = {"insert": sum(w["reason"] == "new" for w in m3["write_set"]),
               "update": sum(w["reason"] == "changed" for w in m3["write_set"])}
    inserted = updated = unchanged_on_write = 0
    committed, error = False, None
    if not ctx.dry_run and m3["write_set"]:
        try:
            results = store.upsert([w["row"] for w in m3["write_set"]])
            committed = True
            inserted = results.count(1)
            updated = results.count(2)
            unchanged_on_write = results.count(0)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
    accepted = len(m3["accepted_ids"])
    skipped = accepted - inserted - updated
    rows = store.readback(m3["accepted_ids"])
    readback = {"table": table, "columns": COLUMNS, "rows": [[r[c] for c in COLUMNS] for r in rows]}
    ev = ctx.put_evidence_json("db-readback.json", readback, "db_readback")
    ops = sorted(store.ops_used)
    ok = (store.user == pol["user"] and f"masswildlife.{table}" in (pol["target"], pol.get("test_target"))
          and set(ops) <= set(pol["allowed_operations"]))
    payload = {"db_user": store.user, "target": f"masswildlife.{table}", "operations_used": ops,
               "dry_run": ctx.dry_run, "planned": planned, "inserted": inserted, "updated": updated,
               "skipped": skipped, "unchanged_on_write": unchanged_on_write, "committed": committed,
               "readback_count": len(rows), "error": error}
    ctx.emit(4, MODULE, in_hash=ctx.last_out_hash, out_hash=hash_obj(readback), evidence=[ev],
             policy_decision="pass" if ok else "violation", rules=RULES, payload=payload)
    return payload
