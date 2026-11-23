"""M3 filtering logic -> PR3. Decides, for every returned record, whether it is accepted and why.

Order of checks per record: malformed (no integer id or created_at), duplicate_in_response (an id seen
earlier in this run), out_of_policy_scope (place_ids does not contain the pinned scope place 141552),
outside_window (created_at not in [window start, window end], inclusive like the API). Survivors are
accepted as new (not in the table), changed (any updatable column differs: flag B, whole-row comparison)
or unchanged. The output (decision list + the rows to write) is one evidence object. Out-of-scope and
outside-window records are never written and are counted. Any such count makes PR3's policy_decision
"violation", which flags the run.
AI-assisted (Claude). Verified by: tests/test_pipeline.py (scope, window, duplicate and changed cases).
"""
from __future__ import annotations

from collections import Counter

from mwia.common.canonical import hash_obj
from mwia.common.timeutil import parse_utc

from .emit import RunContext
from .transform import differs, parse_created, time_zone, to_row

MODULE = "M3:filter"
RULES = ["scope.place_id", "win.created_at"]


def run(ctx: RunContext, plan: dict, observations: list[dict], store) -> dict:
    scope = ctx.cfg.policy["source"]["project"]["scope_place_id"]
    start, end = parse_utc(plan["window"]["start"]), parse_utc(plan["window"]["end"])
    decisions, candidates, seen = [], [], set()
    unknown_tz = 0
    for o in observations:
        oid = o.get("id")
        if not isinstance(oid, int) or not o.get("created_at"):
            decisions.append({"id": oid, "decision": "reject", "reason": "malformed"})
            continue
        if oid in seen:
            decisions.append({"id": oid, "decision": "reject", "reason": "duplicate_in_response"})
            continue
        seen.add(oid)
        if scope not in (o.get("place_ids") or []):
            decisions.append({"id": oid, "decision": "reject", "reason": "out_of_policy_scope"})
            continue
        created = parse_created(o["created_at"])
        if not start <= created <= end:
            decisions.append({"id": oid, "decision": "reject", "reason": "outside_window"})
            continue
        if not time_zone(o.get("observed_time_zone"))[1]:
            unknown_tz += 1
        candidates.append((oid, to_row(o)))
    existing = store.fetch([oid for oid, _ in candidates])
    write_set = []
    for oid, row in candidates:
        if oid not in existing:
            reason = "new"
        elif differs(row, existing[oid]):
            reason = "changed"
        else:
            reason = "unchanged"
        decisions.append({"id": oid, "decision": "accept", "reason": reason})
        if reason != "unchanged":
            write_set.append({"reason": reason, "row": row})
    decisions.sort(key=lambda d: (d["id"] is None, d["id"] if isinstance(d["id"], int) else 0))
    reasons = Counter(d["reason"] for d in decisions)
    counts = {"fetched": len(observations),
              "accepted": {r: reasons.get(r, 0) for r in ("new", "changed", "unchanged")},
              "rejected": {r: reasons.get(r, 0) for r in ("out_of_policy_scope", "outside_window",
                                                         "duplicate_in_response", "malformed")},
              "unknown_time_zones": unknown_tz}
    output = {"decisions": decisions, "write_set": write_set}
    ev = ctx.put_evidence_json("decisions.json", output, "decision_list")
    violation = counts["rejected"]["out_of_policy_scope"] or counts["rejected"]["outside_window"]
    ctx.emit(3, MODULE, in_hash=ctx.last_out_hash, out_hash=hash_obj(output), evidence=[ev],
             policy_decision="violation" if violation else "pass", rules=RULES, payload={"counts": counts})
    return {"counts": counts, "write_set": write_set, "accepted_ids": [d["id"] for d in decisions
                                                                         if d["decision"] == "accept"]}
