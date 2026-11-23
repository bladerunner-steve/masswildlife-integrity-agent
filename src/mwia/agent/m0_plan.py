"""M0 plan generation -> PR0, the run's Minimal Specification and the genesis of its chain.

The plan records: run id, environment, dry-run flag, the time window and how it was chosen (including any
uncovered gap), the declared step sequence, the policy (raw file stored as evidence, parsed copy signed in
the payload), the tool manifest, the expected measurement (agent_id) of every module, the notary key id, and
the previous run's seal hash (PR0.prev_hash). It is signed before any request is built.
AI-assisted (Claude). Verified by: tests/test_pipeline.py.
"""
from __future__ import annotations

from mwia import __version__
from mwia.common.canonical import hash_obj

from .emit import RunContext

MODULE = "M0:plan"
DECLARED_STEPS = [{"step": 0, "module": "M0:plan"}, {"step": 1, "module": "M1:request"},
                  {"step": 2, "module": "M2:response"}, {"step": 3, "module": "M3:filter"},
                  {"step": 4, "module": "M4:db"}, {"step": 5, "module": "M5:complete"}]


def run(ctx: RunContext, window: dict, flags: dict) -> dict:
    cfg = ctx.cfg
    inputs = {"policy_sha256": cfg.policy_sha256, "tool_manifest_sha256": cfg.manifest_sha256, "window": window,
              "flags": flags}
    plan = {
        "run_id": ctx.run_id, "agent_version": __version__,
        "env": {"vault": ctx.vault_env, "db": ctx.db_env, "db_table": flags["db_table"]},
        "dry_run": ctx.dry_run, "window": window, "declared_steps": DECLARED_STEPS,
        "policy_sha256": cfg.policy_sha256, "policy": cfg.policy,
        "tool_manifest_sha256": cfg.manifest_sha256, "tool_manifest": cfg.manifest,
        "expected_measurements": ctx.measure(), "notary_key_id": ctx.key_id, "prev_seal_hash": ctx.prev_hash,
    }
    ev = [ctx.put_evidence_bytes("policy.yaml", cfg.policy_bytes, "policy"),
          ctx.put_evidence_json("plan.json", plan, "plan")]
    ctx.emit(0, MODULE, in_hash=hash_obj(inputs), out_hash=hash_obj(plan), evidence=ev, payload=plan)
    return plan
