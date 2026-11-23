"""M1 API request -> PR1. Builds the exact iNaturalist request from the plan, runs the pre-execution policy
gate, and records the full request (URL, params, headers minus auth) with the gate decision and auth mode.

On a violation the request is not sent: PR1 records policy_decision "violation" with the violated rule ids,
and the run goes straight to M5 with status failed.
Evaluation only (--unsafe-bypass-gate, test vault + test DB enforced by the CLI): the request is sent
anyway and PR1 records "pass" with no violations. This simulates a compromised or misconfigured gate, so the
verifier's policy layer must catch the problem from the recorded parameters, not from the agent's own verdict.
AI-assisted (Claude). Verified by: tests/test_agent_units.py (gate) and tests/test_pipeline.py (violation
and bypass paths).
"""
from __future__ import annotations

from mwia.common.canonical import hash_obj

from . import policy_gate
from .emit import RunContext
from .transform import FIELDS

MODULE = "M1:request"


def build_params(policy: dict, window: dict, overrides: dict | None = None) -> dict:
    src = policy["source"]
    params = {"project_id": src["project"]["id"], window_param(policy, 0): window["start"],
              window_param(policy, 1): window["end"], "order_by": "id", "order": "asc",
              "per_page": policy["rate_limit"]["per_page"], "fields": FIELDS}
    for k, v in (overrides or {}).items():
        if v is None:
            params.pop(k, None)
        else:
            params[k] = v
    return params


def window_param(policy: dict, i: int) -> str:
    return policy["window"]["params"][i]


def run(ctx: RunContext, plan: dict, auth: dict, public_headers: dict, overrides: dict | None, bypass: bool) -> dict:
    policy = ctx.cfg.policy
    src = policy["source"]
    url = f"https://{src['host']}{src['endpoint']}"
    params = build_params(policy, plan["window"], overrides)
    decision, rules, violations = policy_gate.evaluate(src["method"], url, params, policy, plan["window"])
    request = {"method": src["method"], "url": url, "params": params, "headers": public_headers,
               "auth_mode": auth["auth_mode"], "pagination": {"mode": "id_above", "per_page": params.get("per_page")}}
    recorded_decision, recorded_violations = decision, violations
    if bypass:
        recorded_decision, recorded_violations = "pass", []  # simulated compromised gate (eval only)
    gate = {"decision": recorded_decision, "violations": recorded_violations}
    payload = {"request": request, "gate": gate,
               "auth": {k: auth[k] for k in ("auth_mode", "token_exp", "reason")}}
    ev = [ctx.put_evidence_json("request.json", request, "request")]
    ctx.emit(1, MODULE, in_hash=ctx.last_out_hash, out_hash=hash_obj(request), evidence=ev,
             policy_decision=recorded_decision, rules=rules, payload=payload)
    return {"request": request, "send": decision == "pass" or bypass, "true_decision": decision,
            "true_violations": violations}
