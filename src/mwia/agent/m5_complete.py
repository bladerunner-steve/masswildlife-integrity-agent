"""M5 completion decision -> PR5. Reconciles counts across steps, decides success / partial / failed, and
closes the run. The pipeline then asks the notary to seal it.

Checks (each recorded with ok true/false):
  pages_complete         every page was fetched (no error, no truncation)
  fetched_le_total       fetched <= total_results reported by page 1
  fetched_eq_decided     fetched == accepted + rejected (all reasons)
  accepted_eq_db         accepted == inserted + updated + skipped
  plan_matches_db        planned inserts/updates == actual (live runs only)
  db_committed           the transaction committed (live runs with writes)
Status: failed = gate violation or DB error; partial = some check failed; success otherwise.
Flags (alerts that don't change the status): out_of_policy_scope > 0, outside_window > 0, unknown time zones,
an uncovered window gap, token needs refresh.
AI-assisted (Claude). Verified by: tests/test_pipeline.py (success, partial, failed paths).
"""
from __future__ import annotations

from mwia.common.canonical import hash_obj

from .emit import RunContext

MODULE = "M5:complete"


def run(ctx: RunContext, plan: dict, m1: dict, m2: dict | None, m3: dict | None, m4: dict | None,
        auth: dict) -> dict:
    checks, flags, reasons = [], [], []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    status = "success"
    if not m1["send"]:
        status = "failed"
        reasons.append("policy_gate_violation: " + ", ".join(m1["true_violations"]))
    else:
        s = m2["summary"]
        check("pages_complete", s["complete"], str(s["error"] or ""))
        check("fetched_le_total", s["total_results"] is not None and s["fetched"] <= s["total_results"],
              f"fetched={s['fetched']} total_results={s['total_results']}")
        c = m3["counts"]
        accepted, rejected = sum(c["accepted"].values()), sum(c["rejected"].values())
        check("fetched_eq_decided", s["fetched"] == accepted + rejected,
              f"fetched={s['fetched']} accepted={accepted} rejected={rejected}")
        check("accepted_eq_db", accepted == m4["inserted"] + m4["updated"] + m4["skipped"],
              f"accepted={accepted} inserted={m4['inserted']} updated={m4['updated']} skipped={m4['skipped']}")
        if not plan["dry_run"]:
            check("plan_matches_db", m4["planned"] == {"insert": m4["inserted"], "update": m4["updated"]},
                  f"planned={m4['planned']} inserted={m4['inserted']} updated={m4['updated']}")
            if m4["planned"]["insert"] or m4["planned"]["update"]:
                check("db_committed", m4["committed"], m4["error"] or "")
        if m4["error"]:
            status = "failed"
            reasons.append("db_error")
        elif not all(ch["ok"] for ch in checks):
            status = "partial"
            reasons += [ch["name"] for ch in checks if not ch["ok"]]
        for r in ("out_of_policy_scope", "outside_window"):
            if c["rejected"][r]:
                flags.append(f"{r}: {c['rejected'][r]} record(s) rejected")
        if c["unknown_time_zones"]:
            flags.append(f"unknown_time_zone: {c['unknown_time_zones']} record(s) stored with the IANA name")
    if plan["window"].get("gap_seconds"):
        flags.append(f"window_gap: {plan['window']['gap_seconds']} s since the last successful run are not covered")
    if auth.get("warning"):
        flags.append("token_needs_refresh")
    recon = {"status": status, "reasons": reasons, "flags": flags, "checks": checks,
             "steps_executed": [r["body"]["step"] for r in ctx.receipts] + [5],
             "counts": {"total_results": m2["summary"]["total_results"] if m2 else None,
                        "fetched": m2["summary"]["fetched"] if m2 else 0,
                        "accepted": m3["counts"]["accepted"] if m3 else None,
                        "rejected": m3["counts"]["rejected"] if m3 else None,
                        "inserted": m4["inserted"] if m4 else 0, "updated": m4["updated"] if m4 else 0,
                        "skipped": m4["skipped"] if m4 else 0}}
    ev = ctx.put_evidence_json("reconciliation.json", recon, "reconciliation")
    ctx.emit(5, MODULE, in_hash=ctx.last_out_hash, out_hash=hash_obj(recon), evidence=[ev],
             policy_decision="violation" if not m1["send"] else "n/a", payload=recon)
    return recon
