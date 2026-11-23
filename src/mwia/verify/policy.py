"""Layer B: policy-aware verification, implemented independently of the agent's gate.

The policy is re-evaluated from the signed PR0 snapshot (and checked against the policy.yaml bytes stored as
PR0 evidence), never from the policy file on disk. It is also compared with the verifier's own pins
(config/verifier.yaml), so a run that signed a looser policy, or one for another project, still fails.
Checks: the snapshot is consistent and no weaker than the pins; the recorded request (PR1) and every
fetched page (PR2, including each page's actual URL) use the allowed host, endpoint and method, the pinned
project, no forbidden or unknown params, no private fields, the plan's window and the required ordering;
the plan window is at most max_hours + grace; no receipt for PR1, PR2 or PR4 records a violation; PR4 ran
as the pinned DB user against an allowed table using only allowed operations (SELECT only for a dry run);
the executed step sequence equals the declared one; and no out-of-scope or out-of-window observation was
accepted or reached the database.
AI-assisted (Claude). Verified by: tests/test_verify.py (signed-but-unauthorized, plan deviation, long
window, out-of-scope cases).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import yaml

from mwia.common.canonical import sha256_hex
from mwia.common.timeutil import parse_utc

from .findings import Finding


def _f(code, detail="", step=None, module=None):
    return Finding("B", code, "fail", detail, step, module)


def _evidence(vault, body, role):
    out = []
    for e in body["evidence"]:
        if e["role"] == role:
            data = vault._read(e["key"])
            if data is not None and sha256_hex(data) == e["sha256"]:
                out.append(data)
    return out


def _check_request(method, url, params, policy, pins, window, step, module, extra_allowed=()) -> list[Finding]:
    out = []
    u = urlsplit(url or "")
    src = policy.get("source", {})
    if method != pins["method"] or u.scheme != "https" or u.hostname != pins["host"] or u.path != pins["endpoint"]:
        out.append(_f("request_wrong_target", f"{method} {u.scheme}://{u.hostname}{u.path}", step, module))
    if str(params.get("project_id")) != str(pins["project_id"]):
        out.append(_f("request_wrong_project", f"project_id={params.get('project_id')}", step, module))
    bad = sorted(set(params) & (set(pins["forbidden_params"]) | set(src.get("forbidden_params", []))))
    if bad:
        out.append(_f("request_forbidden_param", ", ".join(bad), step, module))
    allowed = set(src.get("allowed_params", [])) | set(extra_allowed)
    unknown = sorted(p for p in params if p not in allowed)
    if unknown:
        out.append(_f("request_unknown_param", ", ".join(unknown), step, module))
    fields = str(params.get("fields", ""))
    if any(f in fields for f in pins["forbidden_fields"]):
        out.append(_f("request_forbidden_field", step=step, module=module))
    if str(params.get("order_by")) != "id" or str(params.get("order")) != "asc":
        out.append(_f("request_order", step=step, module=module))
    try:
        d1, d2 = parse_utc(params.get("created_d1")), parse_utc(params.get("created_d2"))
        cap = timedelta(hours=pins["max_window_hours"], minutes=pins["max_grace_minutes"])
        if (params.get("created_d1"), params.get("created_d2")) != (window.get("start"), window.get("end")) \
                or d2 < d1 or d2 - d1 > cap:
            out.append(_f("request_window", f"{params.get('created_d1')} -> {params.get('created_d2')}", step, module))
    except (TypeError, ValueError):
        out.append(_f("request_window", "missing or malformed window parameters", step, module))
    return out


def _url_params(url: str) -> dict:
    return {k: v[0] if len(v) == 1 else v for k, v in parse_qs(urlsplit(url or "").query, keep_blank_values=True).items()}


def check(run, chain: list[dict], vctx) -> list[Finding]:
    out: list[Finding] = []
    pins = vctx.pins
    if not chain:
        return [_f("plan_deviation", "no signed plan to evaluate", 0, "M0:plan")]
    by_step = {r["body"]["step"]: r["body"] for r in chain}
    pr0 = chain[0]["body"]
    plan = pr0["payload"]
    policy = plan.get("policy") or {}
    window = plan.get("window") or {}
    # snapshot consistency (raw policy.yaml evidence vs the parsed policy signed in the plan)
    raw = _evidence(vctx.vault, pr0, "policy")
    if not raw or sha256_hex(raw[0]) != plan.get("policy_sha256") or yaml.safe_load(raw[0]) != policy:
        out.append(_f("policy_snapshot_inconsistent", step=0, module="M0:plan"))
    # snapshot vs pins
    src, win, db = policy.get("source", {}), policy.get("window", {}), policy.get("database", {})
    proj = src.get("project", {})
    weaker = []
    for name, got, want in (("host", src.get("host"), pins["host"]), ("endpoint", src.get("endpoint"), pins["endpoint"]),
                            ("method", src.get("method"), pins["method"]), ("project.id", proj.get("id"), pins["project_id"]),
                            ("project.slug", proj.get("slug"), pins["project_slug"]),
                            ("project.scope_place_id", proj.get("scope_place_id"), pins["scope_place_id"]),
                            ("window.field", win.get("field"), pins["window_field"]), ("database.user", db.get("user"), pins["db_user"])):
        if got != want:
            weaker.append(f"{name}={got!r}")
    if (win.get("max_hours") or 1e9) > pins["max_window_hours"] or (win.get("grace_minutes") or 1e9) > pins["max_grace_minutes"]:
        weaker.append("window limits")
    if not set(db.get("allowed_operations", ["?"])) <= set(pins["allowed_db_operations"]):
        weaker.append("database.allowed_operations")
    if not set(pins["forbidden_params"]) <= set(src.get("forbidden_params", [])):
        weaker.append("source.forbidden_params")
    if not set(pins["forbidden_fields"]) <= set(src.get("forbidden_fields", [])):
        weaker.append("source.forbidden_fields")
    if weaker:
        out.append(_f("policy_weaker_than_pins", ", ".join(weaker), 0, "M0:plan"))
    # plan window
    try:
        cap = timedelta(hours=pins["max_window_hours"], minutes=pins["max_grace_minutes"])
        if parse_utc(window["end"]) - parse_utc(window["start"]) > cap:
            out.append(_f("window_too_long", f"{window['start']} -> {window['end']}", 0, "M0:plan"))
    except (KeyError, TypeError, ValueError):
        out.append(_f("window_too_long", "plan window missing or malformed", 0, "M0:plan"))
    # step sequence
    executed = [r["body"]["module"] for r in chain]
    declared = [s.get("module") for s in plan.get("declared_steps", [])]
    ref = pins["declared_steps"]
    truncated_prefix = run.seal is None and executed == ref[:len(executed)] and declared == ref
    if (declared != ref or executed != declared) and not truncated_prefix:
        # An unsealed run that stopped part-way (a prefix of the plan) is incomplete, not deviant. Layer C
        # reports its missing steps. Anything else that departs from the plan is a deviation.
        i = next((k for k in range(max(len(ref), len(executed)))
                  if k >= len(ref) or k >= len(executed) or ref[k] != executed[k]), 0)
        out.append(_f("plan_deviation", f"declared {declared}, executed {executed}", i,
                      ref[i] if i < len(ref) else executed[i]))
    # recorded request (PR1) and pages (PR2)
    if 1 in by_step:
        req = by_step[1]["payload"].get("request", {})
        out += _check_request(req.get("method"), req.get("url"), req.get("params", {}), policy, pins, window, 1, "M1:request")
    if 2 in by_step:
        b2 = by_step[2]
        for p in b2["payload"].get("pages", []):
            out += _check_request("GET", p.get("url"), p.get("params", {}), policy, pins, window, 2, "M2:response",
                                  extra_allowed=("id_above",))
            if {k: str(v) for k, v in p.get("params", {}).items()} != {k: str(v) for k, v in _url_params(p.get("url")).items()}:
                out.append(_f("page_url_mismatch", f"page {p.get('n')}", 2, "M2:response"))
    for s in (1, 2, 4):
        if s in by_step and by_step[s]["policy_decision"] == "violation":
            out.append(_f("agent_recorded_violation", f"PR{s} recorded a violation", s, by_step[s]["module"]))
    # database (PR4)
    if 4 in by_step:
        p4 = by_step[4]["payload"]
        if p4.get("db_user") != pins["db_user"]:
            out.append(_f("db_user", str(p4.get("db_user")), 4, "M4:db"))
        targets = set(pins["db_targets"]) & {db.get("target"), db.get("test_target")}
        if p4.get("target") not in targets:
            out.append(_f("db_target", str(p4.get("target")), 4, "M4:db"))
        ops = set(p4.get("operations_used", []))
        if not ops <= set(pins["allowed_db_operations"]) & set(db.get("allowed_operations", [])):
            out.append(_f("db_operations", ", ".join(sorted(ops)), 4, "M4:db"))
        if plan.get("dry_run") and (ops - {"SELECT"} or p4.get("inserted") or p4.get("updated")):
            out.append(_f("dry_run_violated", step=4, module="M4:db"))
    # what was accepted / written vs the raw records
    raw_by_id = {}
    if 2 in by_step:
        for data in _evidence(vctx.vault, by_step[2], "raw_response"):
            try:
                for o in json.loads(data).get("results", []):
                    raw_by_id.setdefault(o.get("id"), o)
            except ValueError:
                pass
    # Without the decision list there is nothing to compare the writes against. That is missing evidence
    # (layer C), not a policy violation, so the accepted-vs-written check runs only when the list is present.
    accepted, have_decisions = set(), False
    if 3 in by_step:
        for data in _evidence(vctx.vault, by_step[3], "decision_list"):
            accepted = {d["id"] for d in json.loads(data).get("decisions", []) if d.get("decision") == "accept"}
            have_decisions = True
    scope = pins["scope_place_id"]
    try:
        w1, w2 = parse_utc(window["start"]), parse_utc(window["end"])
    except (KeyError, TypeError, ValueError):
        w1 = w2 = None
    for oid in sorted(i for i in accepted if i in raw_by_id):
        o = raw_by_id[oid]
        if scope not in (o.get("place_ids") or []):
            out.append(_f("out_of_scope_accepted", f"observation {oid}", 3, "M3:filter"))
        elif w1 and not w1 <= datetime.fromisoformat(o["created_at"]).astimezone(timezone.utc) <= w2:
            out.append(_f("outside_window_accepted", f"observation {oid}", 3, "M3:filter"))
    if 4 in by_step:
        for data in _evidence(vctx.vault, by_step[4], "db_readback"):
            rb = json.loads(data)
            idx = rb.get("columns", []).index("id") if "id" in rb.get("columns", []) else 0
            for row in rb.get("rows", []):
                oid = row[idx]
                if have_decisions and oid not in accepted:
                    out.append(_f("unaccepted_record_written", f"observation {oid}", 4, "M4:db"))
                elif oid in raw_by_id and scope not in (raw_by_id[oid].get("place_ids") or []):
                    out.append(_f("out_of_scope_written", f"observation {oid}", 4, "M4:db"))
    return out
