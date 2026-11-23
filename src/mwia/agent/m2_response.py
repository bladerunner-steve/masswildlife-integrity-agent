"""M2 API response -> PR2. Executes the request with keyset pagination (order_by=id asc, id_above=<last id>),
stores every raw response body as a raw_response evidence object, and records per page: exact params, final
URL, status, total_results, result count, first and last id, timing and attempts. It also records the overall
total_results (from page 1), the number fetched and the page count.

Each page's params go through the policy gate before sending (unless the eval-only bypass is active). A
page that still fails after retries stops pagination and is recorded as an error. M5 then marks the run
partial.
AI-assisted (Claude). Verified by: tests/test_pipeline.py (multi-page fixture, failed-page path) and
tests/test_agent_units.py (HTTP client).
"""
from __future__ import annotations

import json

from mwia.common.canonical import hash_obj

from . import policy_gate
from .emit import RunContext
from .http import HttpError

MODULE = "M2:response"
MAX_PAGES = 500


def run(ctx: RunContext, plan: dict, req: dict, client, bypass: bool) -> dict:
    policy = ctx.cfg.policy
    request = req["request"]
    base = dict(request["params"])
    per_page = int(base.get("per_page", 200))
    pages, evidence, observations = [], [], []
    error, total_results, id_above = None, None, None
    decision, rules, page_violations = "pass", policy_gate.RULES, []
    for n in range(1, MAX_PAGES + 1):
        params = dict(base)
        if id_above is not None:
            params["id_above"] = id_above
        d, _, v = policy_gate.evaluate(request["method"], request["url"], params, policy, plan["window"])
        if d != "pass" and not bypass:
            decision, page_violations = "violation", v
            error = {"page": n, "error": "page request violates policy", "violations": v}
            break
        try:
            body, rec = client.get(request["url"], params)
        except HttpError as e:
            error = {"page": n, "error": str(e), **{k: e.record.get(k) for k in ("status", "attempts")}}
            break
        doc = json.loads(body)
        results = doc.get("results", [])
        ev = ctx.put_evidence_bytes(f"page-{n:04d}.json", body, "raw_response")
        evidence.append(ev)
        if total_results is None:
            total_results = doc.get("total_results")
        pages.append({"n": n, "params": params, "url": rec["url"], "status": rec["status"],
                      "fetched_at": rec["fetched_at"], "elapsed_ms": rec["elapsed_ms"], "attempts": rec["attempts"],
                      "total_results": doc.get("total_results"), "results": len(results),
                      "first_id": results[0]["id"] if results else None,
                      "last_id": results[-1]["id"] if results else None, "sha256": ev["sha256"], "key": ev["key"]})
        observations.extend(results)
        if len(results) < per_page:
            break
        id_above = results[-1]["id"]
    else:
        error = {"page": MAX_PAGES + 1, "error": f"stopped after {MAX_PAGES} pages"}
    summary = {"pages": pages, "page_count": len(pages), "total_results": total_results,
               "fetched": len(observations), "complete": error is None, "error": error}
    ev_sum = ctx.put_evidence_json("response-summary.json", summary, "output")
    if bypass:
        decision, page_violations = "pass", []
    ctx.emit(2, MODULE, in_hash=ctx.last_out_hash, out_hash=hash_obj(summary), evidence=evidence + [ev_sum],
             policy_decision=decision, rules=rules,
             payload={**summary, "gate_violations": page_violations})
    return {"summary": summary, "observations": observations}
