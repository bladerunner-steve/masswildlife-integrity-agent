"""Layer C: evidence-aware verification. Every finding here is "insufficient", never "fail": missing, stale
or self-contradictory evidence means the run can't be vouched for, but it doesn't prove tampering (layers A
and B decide that).

Checks: all six steps left a receipt; each step's mandatory evidence was recorded (PR0 plan + policy, PR1
request, PR2 one raw page per recorded page + summary, PR3 decision list, PR4 DB readback, PR5
reconciliation); the raw pages match what PR2 recorded about them (result counts, total_results, ids) and
form a gap-free keyset sequence that ran to the end; the counts reconcile (total_results >= fetched;
fetched = accepted + rejected; accepted = inserted + updated + skipped; the PR3/PR4/PR5 numbers agree with
the evidence); the readback holds every accepted record (live runs) and matches the written rows; each
response was fetched after the window closed and within max_fetch_lag_minutes; accepted observations fall
inside the window; and PR5's status follows from the evidence.
AI-assisted (Claude). Verified by: tests/test_verify.py (omitted page, unreconcilable counts, stale cases).
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from mwia.common.canonical import sha256_hex
from mwia.common.timeutil import parse_utc

from .findings import Finding

MANDATORY = {0: ["plan", "policy"], 1: ["request"], 2: ["output"], 3: ["decision_list"], 4: ["db_readback"],
             5: ["reconciliation"]}
MODULES = {0: "M0:plan", 1: "M1:request", 2: "M2:response", 3: "M3:filter", 4: "M4:db", 5: "M5:complete"}


def _f(code, detail="", step=None):
    return Finding("C", code, "insufficient", detail, step, MODULES.get(step))


def _load(vault, ev):
    data = vault._read(ev["key"])
    if data is None or sha256_hex(data) != ev["sha256"]:
        return None
    return data


def check(run, chain: list[dict], vctx) -> list[Finding]:
    out: list[Finding] = []
    by_step = {r["body"]["step"]: r["body"] for r in chain}
    missing_steps = [s for s in range(6) if s not in by_step]
    if missing_steps:
        out.append(_f("steps_missing", f"no receipt for step(s) {missing_steps}", missing_steps[0]))
    for s, roles in MANDATORY.items():
        if s in by_step:
            have = Counter(e["role"] for e in by_step[s]["evidence"])
            for role in roles:
                if not have.get(role):
                    out.append(_f("mandatory_evidence_missing", f"PR{s} has no {role} evidence", s))
    if not chain:
        return out
    plan = chain[0]["body"]["payload"]
    window = plan.get("window", {})
    try:
        w1, w2 = parse_utc(window["start"]), parse_utc(window["end"])
    except (KeyError, TypeError, ValueError):
        w1 = w2 = None
    raw_ids: list = []
    fetched_raw = None
    # ---- PR2 pages
    if 2 in by_step:
        b2 = by_step[2]
        s2 = b2["payload"]
        raw_ev = [e for e in b2["evidence"] if e["role"] == "raw_response"]
        by_sha = {e["sha256"]: e for e in raw_ev}
        pages = s2.get("pages", [])
        if len(raw_ev) != len(pages) or s2.get("page_count") != len(pages):
            out.append(_f("raw_page_missing", f"{len(pages)} pages recorded, {len(raw_ev)} kept", 2))
        fetched_raw = 0
        lag = timedelta(minutes=vctx.cfg["evidence"]["max_fetch_lag_minutes"])
        per_page = None
        for i, p in enumerate(pages):
            ev = by_sha.get(p.get("sha256"))
            data = _load(vctx.vault, ev) if ev else None
            if data is None:
                out.append(_f("raw_page_missing", f"page {p.get('n')}", 2))
                continue
            try:
                doc = json.loads(data)
                res = doc.get("results", [])
            except ValueError:
                out.append(_f("raw_page_inconsistent", f"page {p.get('n')} is not JSON", 2))
                continue
            ids = [o.get("id") for o in res]
            if len(res) != p.get("results") or doc.get("total_results") != p.get("total_results") \
                    or (ids and (ids[0] != p.get("first_id") or ids[-1] != p.get("last_id"))):
                out.append(_f("raw_page_inconsistent", f"page {p.get('n')}", 2))
            if i == 0 and doc.get("total_results") != s2.get("total_results"):
                out.append(_f("raw_page_inconsistent", "total_results differs from page 1", 2))
            fetched_raw += len(res)
            raw_ids += ids
            per_page = int(p.get("params", {}).get("per_page", 0) or 0)
            if i > 0 and str(p.get("params", {}).get("id_above")) != str(pages[i - 1].get("last_id")):
                out.append(_f("pagination_incomplete", f"page {p.get('n')} does not continue page {pages[i - 1].get('n')}", 2))
            try:
                t = parse_utc(p["fetched_at"])
                if w2 and not (w2 - timedelta(minutes=1) <= t <= w2 + lag):
                    out.append(_f("stale_response", f"page {p.get('n')} fetched {p['fetched_at']}", 2))
            except (KeyError, TypeError, ValueError):
                out.append(_f("stale_response", f"page {p.get('n')} has no fetch time", 2))
        if not s2.get("complete", False):
            out.append(_f("pages_incomplete", str(s2.get("error")), 2))
        elif pages and per_page and pages[-1].get("results", 0) >= per_page:
            out.append(_f("pagination_incomplete", "the last page was full, so more pages may exist", 2))
        if s2.get("total_results") is not None and s2.get("fetched", 0) > s2["total_results"]:
            out.append(_f("counts_unreconciled", f"fetched {s2.get('fetched')} > total_results {s2['total_results']}", 2))
        if s2.get("fetched") != fetched_raw:
            out.append(_f("counts_unreconciled", f"PR2 says {s2.get('fetched')} fetched, raw pages hold {fetched_raw}", 2))
    # ---- PR3 decisions
    decisions, write_set = None, []
    if 3 in by_step:
        b3 = by_step[3]
        for e in b3["evidence"]:
            if e["role"] == "decision_list":
                data = _load(vctx.vault, e)
                if data is not None:
                    doc = json.loads(data)
                    decisions, write_set = doc.get("decisions", []), doc.get("write_set", [])
        if decisions is not None:
            reasons = Counter(d["reason"] for d in decisions)
            counts = b3["payload"].get("counts", {})
            acc = {r: reasons.get(r, 0) for r in ("new", "changed", "unchanged")}
            if counts.get("accepted") != acc or sum(counts.get("rejected", {}).values()) != \
                    sum(n for r, n in reasons.items() if r not in acc):
                out.append(_f("counts_unreconciled", "PR3 counts differ from its decision list", 3))
            if fetched_raw is not None and len(decisions) != fetched_raw:
                out.append(_f("counts_unreconciled", f"{fetched_raw} records fetched, {len(decisions)} decided", 3))
            if raw_ids and sorted(map(str, raw_ids)) != sorted(str(d["id"]) for d in decisions):
                out.append(_f("counts_unreconciled", "decided records differ from fetched records", 3))
            if len(write_set) != acc["new"] + acc["changed"]:
                out.append(_f("counts_unreconciled", "write set size differs from new + changed", 3))
            if w1:
                for w in write_set:
                    try:
                        c = datetime.strptime(w["row"]["created_at"], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
                        if not w1 <= c <= w2:
                            out.append(_f("stale_observation", f"observation {w['row']['id']}", 3))
                    except (KeyError, ValueError):
                        out.append(_f("stale_observation", "observation without a parseable created_at", 3))
    accepted_ids = [d["id"] for d in decisions or [] if d.get("decision") == "accept"]
    # ---- PR4 database
    if 4 in by_step:
        p4 = by_step[4]["payload"]
        if decisions is not None and len(accepted_ids) != p4.get("inserted", 0) + p4.get("updated", 0) + p4.get("skipped", 0):
            out.append(_f("counts_unreconciled", f"accepted {len(accepted_ids)} != inserted + updated + skipped", 4))
        rb = None
        for e in by_step[4]["evidence"]:
            if e["role"] == "db_readback":
                data = _load(vctx.vault, e)
                rb = json.loads(data) if data is not None else None
        if rb is not None:
            cols = rb.get("columns", [])
            rows = {r[cols.index("id")]: dict(zip(cols, r)) for r in rb.get("rows", [])} if "id" in cols else {}
            if p4.get("readback_count") != len(rows):
                out.append(_f("counts_unreconciled", "PR4 readback_count differs from the readback", 4))
            if not plan.get("dry_run") and decisions is not None and set(rows) != set(accepted_ids):
                out.append(_f("readback_incomplete", f"{len(set(accepted_ids) - set(rows))} accepted record(s) "
                                                     f"not in the database readback", 4))
            if not plan.get("dry_run"):
                for w in write_set:
                    got = rows.get(w["row"].get("id"))
                    if got is not None and any(got.get(c) != v for c, v in w["row"].items()
                                               if c in got and not c.startswith("private_")):
                        out.append(_f("readback_mismatch", f"observation {w['row'].get('id')}", 4))
    # ---- PR5 completion
    if 5 in by_step:
        rec = by_step[5]["payload"]
        c = rec.get("counts", {})
        if 4 in by_step:
            p4 = by_step[4]["payload"]
            if (c.get("inserted"), c.get("updated"), c.get("skipped")) != (p4.get("inserted"), p4.get("updated"), p4.get("skipped")):
                out.append(_f("completion_inconsistent", "PR5 counts differ from PR4", 5))
        if 2 in by_step and c.get("fetched") != by_step[2]["payload"].get("fetched"):
            out.append(_f("completion_inconsistent", "PR5 fetched differs from PR2", 5))
        problems = [f for f in out if f.code != "steps_missing"]
        if rec.get("status") == "success" and (problems or missing_steps):
            out.append(_f("completion_inconsistent", "the run claims success, but its evidence does not support it", 5))
    return out
