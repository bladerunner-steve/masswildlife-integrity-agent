"""Verifier engine: loads the trust inputs once per vault, runs the enabled layers on a run and applies the
outcome rules.

Configurations: A = crypto, B = crypto+policy, C = crypto+policy+evidence. Each verdict records which
configuration produced it. Outcome rules (exactly three statuses):
  VERIFICATION FAILED     any "fail" finding in an enabled layer
  INSUFFICIENT EVIDENCE   no failures, but at least one "insufficient" finding
  VERIFIED WITHIN SCOPE   no findings
A configuration only ever sees what its layers can see: config A never runs the policy or evidence checks.
The localized failure is the earliest step (in step order) with a failing finding.
AI-assisted (Claude). Verified by: tests/test_verify.py.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mwia.common.canonical import ZERO_HASH
from mwia.common.keyring import load_trusted_keys
from mwia.common.timeutil import parse_utc, utc_now
from mwia.vault.anchor import check_anchors, read_anchors

from . import crypto, evidence, policy
from .reader import ReadOnlyLocalVault, RunObjects, runs_in_vault

MODES = {"crypto": ("A",), "crypto+policy": ("A", "B"), "crypto+policy+evidence": ("A", "B", "C")}
CONFIG_LABEL = {"crypto": "A", "crypto+policy": "B", "crypto+policy+evidence": "C"}
FAILED, INSUFFICIENT, VERIFIED = "VERIFICATION FAILED", "INSUFFICIENT EVIDENCE", "VERIFIED WITHIN SCOPE"
STEP_MODULES = ["M0:plan", "M1:request", "M2:response", "M3:filter", "M4:db", "M5:complete"]


@dataclass
class VerifyContext:
    vault: ReadOnlyLocalVault
    trusted: dict
    retired_at: dict
    cfg: dict
    pins: dict
    runs: list[RunObjects]
    ledger_problems: list
    anchor_problems: list
    anchored_seals: set | None
    nonce_owner: dict = field(default_factory=dict)
    hash_owner: dict = field(default_factory=dict)
    truncated_severity: str = "insufficient"

    def previous_seal_hash(self, run: RunObjects) -> str:
        prev = ZERO_HASH
        for r in self.runs:
            if r.run_id == run.run_id:
                return prev
            if r.seal and isinstance(r.seal, dict) and r.seal.get("seal_hash"):
                prev = r.seal["seal_hash"]
        return prev


def load_context(vault_root: Path, public_keys: Path, anchors_file: Path | None, verifier_cfg: Path) -> VerifyContext:
    vault = ReadOnlyLocalVault(vault_root)
    cfg = yaml.safe_load(Path(verifier_cfg).read_text(encoding="utf-8"))
    trusted = load_trusted_keys(public_keys)
    retired = {}
    ring = Path(public_keys) / "keyring.json"
    if ring.is_file():
        for k in json.loads(ring.read_text(encoding="utf-8")).get("keys", []):
            if k.get("retired_at"):
                retired[k["key_id"]] = parse_utc(k["retired_at"])
    runs = runs_in_vault(vault)
    if anchors_file is not None:
        entries, _ = read_anchors(anchors_file)
        anchor_problems, anchored = check_anchors(vault, anchors_file), {e["seal_hash"] for e in entries}
    else:
        anchor_problems, anchored = [], None
    ctx = VerifyContext(vault, trusted, retired, cfg, cfg["pins"], runs, vault.verify(), anchor_problems, anchored,
                        truncated_severity="fail" if cfg.get("truncated_trace") == "failed" else "insufficient")
    for r in runs:
        for obj in r.receipt_keys.values():
            try:
                ctx.nonce_owner.setdefault(obj["body"]["nonce"], set()).add(r.run_id)
                ctx.hash_owner.setdefault(obj["receipt_hash"], set()).add(r.run_id)
            except (TypeError, KeyError):
                pass
    return ctx


def _status(findings) -> str:
    if any(f.severity == "fail" for f in findings):
        return FAILED
    if findings:
        return INSUFFICIENT
    return VERIFIED


def verify_run(ctx: VerifyContext, run: RunObjects, mode: str = "crypto+policy+evidence") -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {list(MODES)}")
    t0 = time.perf_counter()
    layers = MODES[mode]
    a, chain = crypto.check(run, ctx)
    found = {"A": a}
    if "B" in layers:
        found["B"] = policy.check(run, chain, ctx)
    if "C" in layers:
        found["C"] = evidence.check(run, chain, ctx)
    allf = [f for fs in found.values() for f in fs]
    status = _status(allf)
    fails = sorted((f for f in allf if f.severity == "fail"), key=lambda f: (f.step is None, f.step or 0))
    first = fails[0].to_dict() if fails else None
    by_step = {r["body"]["step"]: r["body"] for r in chain}
    steps = []
    for s, mod in enumerate(STEP_MODULES):
        row = {"step": s, "module": mod, "present": s in by_step}
        for L in ("A", "B", "C"):
            if L not in found:
                row[L] = "not_checked"
                continue
            fs = [f for f in found[L] if f.step == s]
            row[L] = "fail" if any(f.severity == "fail" for f in fs) else ("insufficient" if fs else
                                                                           ("pass" if s in by_step else "absent"))
        steps.append(row)
    pr0 = by_step.get(0, {}).get("payload", {})
    pr1 = by_step.get(1, {}).get("payload", {})
    pr5 = by_step.get(5, {}).get("payload", {})
    return {
        "run_id": run.run_id, "run_date": run.run_date, "mode": mode, "config": CONFIG_LABEL[mode],
        "status": status, "first_failure": first,
        "findings": {L: [f.to_dict() for f in fs] for L, fs in found.items()},
        "steps": steps, "sealed": run.seal is not None,
        "window": pr0.get("window"), "dry_run": pr0.get("dry_run"), "env": pr0.get("env"),
        "counts": pr5.get("counts"), "run_status": pr5.get("status"), "flags": pr5.get("flags", []),
        "token_needs_refresh": (pr1.get("auth") or {}).get("reason") in ("token_expired", "token_expires_soon",
                                                                        "token_malformed"),
        "trusted_key_ids": sorted(ctx.trusted), "verified_at": utc_now(),
        "verifier_version": ctx.cfg.get("verifier_version"),
        "latency_ms": round((time.perf_counter() - t0) * 1000, 3),
    }


def find_run(ctx: VerifyContext, run_id: str | None) -> RunObjects:
    if not ctx.runs:
        raise LookupError("the vault contains no runs")
    if run_id is None:
        return ctx.runs[-1]
    for r in ctx.runs:
        if r.run_id == run_id:
            return r
    raise LookupError(f"run {run_id} is not in the vault")
