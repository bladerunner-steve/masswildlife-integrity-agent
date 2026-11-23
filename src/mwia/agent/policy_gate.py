"""Pre-execution policy gate: checks an outgoing iNaturalist request against the policy before it is sent.

Rule ids (recorded in PR1/PR2 as policy_rules_evaluated; violations listed by id):
  src.method, src.scheme, src.host, src.endpoint, src.project, src.forbidden_param, src.allowed_params,
  src.required_params, src.forbidden_fields, win.params, win.order, win.max_length, rate.per_page
The window rules compare created_d1/created_d2 with the plan's window and check the length is at most
max_hours + grace_minutes. This is the agent's own gate. The verifier re-implements policy evaluation
independently (layer B) from the signed PR0 policy snapshot.
AI-assisted (Claude). Verified by: tests/test_agent_units.py (one test per rule).
"""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlsplit

from mwia.common.timeutil import parse_utc

RULES = ["src.method", "src.scheme", "src.host", "src.endpoint", "src.project", "src.forbidden_param",
         "src.allowed_params", "src.required_params", "src.forbidden_fields", "win.params", "win.order",
         "win.max_length", "rate.per_page"]


def evaluate(method: str, url: str, params: dict, policy: dict, window: dict) -> tuple[str, list[str], list[str]]:
    """Return (decision 'pass'|'violation', rules_evaluated, violated_rule_ids)."""
    src, win = policy["source"], policy["window"]
    u = urlsplit(url)
    v: list[str] = []
    if method != src["method"]:
        v.append("src.method")
    if u.scheme != "https":
        v.append("src.scheme")
    if u.hostname != src["host"]:
        v.append("src.host")
    if u.path != src["endpoint"]:
        v.append("src.endpoint")
    if str(params.get("project_id")) != str(src["project"]["id"]):
        v.append("src.project")
    if any(p in params for p in src["forbidden_params"]):
        v.append("src.forbidden_param")
    if any(p not in src["allowed_params"] for p in params):
        v.append("src.allowed_params")
    if any(str(params.get(k)) != str(val) for k, val in src.get("required_params", {}).items()):
        v.append("src.required_params")
    fields = str(params.get("fields", ""))
    if any(f in fields for f in src.get("forbidden_fields", [])):
        v.append("src.forbidden_fields")
    d1, d2 = params.get(win["params"][0]), params.get(win["params"][1])
    if d1 != window["start"] or d2 != window["end"]:
        v.append("win.params")
    try:
        t1, t2 = parse_utc(d1), parse_utc(d2)
        if t2 < t1:
            v.append("win.order")
        if t2 - t1 > timedelta(hours=win["max_hours"], minutes=win["grace_minutes"]):
            v.append("win.max_length")
    except (TypeError, ValueError):
        v += ["win.order", "win.max_length"]
    try:
        if int(params.get("per_page", 0)) > int(policy["rate_limit"]["per_page"]):
            v.append("rate.per_page")
    except (TypeError, ValueError):
        v.append("rate.per_page")
    return ("violation" if v else "pass"), list(RULES), sorted(set(v), key=RULES.index)
