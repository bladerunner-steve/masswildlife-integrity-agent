"""The labelled evaluation scenarios (docs/PROJECT_BRIEF.md Part A, Phase 5 table).

Every scenario produces one trace with the real pipeline (see harness.py), then optionally manipulates
the vault afterwards. Its ground-truth label comes from how the trace was made, never from the verifier:
  legitimate        clean authorized run (normal or dry run)
  tampered          naive artifact tamper, log rewriting, forward recompute, key forgery, replay
  policy_violation  signed but unauthorized request, plan deviation, window > 24 h (all validly signed)
  insufficient      omitted evidence, unreconcilable counts, truncated trace (label decided by the author)
truth_step is the step where the manipulation or violation first sits, used for localization accuracy.
It is None where localization doesn't apply. Each repetition draws its variant (which object, step or
parameter) from a seeded RNG, so the 30 repetitions differ but are reproducible.
AI-assisted (Claude). Verified by: tests/test_eval.py (every scenario builds and carries its label).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from random import Random
from typing import Callable

from mwia.common.canonical import hash_obj, sha256_hex

from harness import Trace

PRIMARY = {1: "request", 2: "output", 3: "decision_list", 4: "db_readback", 5: "reconciliation"}


@dataclass(frozen=True)
class Scenario:
    name: str
    label: str
    build: Callable[[Trace, Random, dict], tuple[dict, int | None, str]]


# ---------------- helpers ----------------

def _pick_evidence(t: Trace, rep: dict, rng: Random):
    step = rng.choice([1, 2, 2, 3, 4])                    # raw pages are the most common evidence
    path = t.key_of(rep, step)
    obj = t.read(path)
    evs = obj["body"]["evidence"]
    if step == 2:
        evs = [e for e in evs if e["role"] == "raw_response"] or evs
    ev = rng.choice(evs)
    return step, path, obj, ev


def _alter(t: Trace, ev: dict) -> str:
    """Change one evidence object's bytes (still valid JSON) and return its new hash."""
    p = t.vault_root / ev["key"]
    data = p.read_bytes()
    data = data[:-1] + b' }' if data.endswith(b"}") else data + b" "
    p.write_bytes(data)
    return sha256_hex(data)


# ---------------- legitimate ----------------

def clean(t, rng, ctx):
    dry = rng.random() < 0.3
    return t.run(*(["--dry-run"] if dry else [])), None, "dry_run" if dry else "normal"


# ---------------- tampered (after the fact) ----------------

def naive_tamper(t, rng, ctx):
    rep = t.run()
    step, _, _, ev = _pick_evidence(t, rep, rng)
    _alter(t, ev)
    return rep, step, f"evidence PR{step} {ev['role']}"


def log_rewrite(t, rng, ctx):
    rep = t.run()
    step, path, obj, ev = _pick_evidence(t, rep, rng)
    new = _alter(t, ev)
    for e in obj["body"]["evidence"]:
        if e["key"] == ev["key"]:
            e["sha256"] = new
    if ev["role"] == PRIMARY.get(step):
        obj["body"]["out_hash"] = new
    obj["receipt_hash"] = hash_obj(obj["body"])           # hash recomputed; the signature can't be
    t.write(path, obj)
    return rep, step, f"evidence + receipt PR{step} {ev['role']}"


def forward_recompute(t, rng, ctx):
    rep = t.run()
    step, path, obj, ev = _pick_evidence(t, rep, rng)
    new = _alter(t, ev)
    for e in obj["body"]["evidence"]:
        if e["key"] == ev["key"]:
            e["sha256"] = new
    if ev["role"] == PRIMARY.get(step):
        obj["body"]["out_hash"] = new
        if step < 5:
            nxt = t.key_of(rep, step + 1)
            n = t.read(nxt)
            n["body"]["in_hash"] = new
            t.write(nxt, n)
    t.write(path, obj)
    t.resign(rep, step, *ctx["attacker"])               # rebuild the chain and seal from the tampered step
    return rep, step, f"recompute from PR{step} ({ev['role']})"


def key_forgery(t, rng, ctx):
    rep = t.run()
    t.resign(rep, 0, *ctx["attacker"])
    return rep, 0, "all receipts re-signed with an untrusted key"


def replay(t, rng, ctx):
    first = t.run()
    t.now += timedelta(hours=1)
    second = t.run()
    step = rng.choice([1, 2, 3, 4])
    t.write(t.key_of(second, step), t.read(t.key_of(first, step)))
    return second, step, f"PR{step} replaced by the previous run's PR{step}"


# ---------------- policy violations (validly signed) ----------------

UNAUTHORIZED = [["place_id=1"], ["lat=42.36", "lng=-71.06", "radius=50"], ["project_id=12345"],
                ["user_id=1001"],["nelat=42.9", "nelng=-70.5", "swlat=41.2", "swlng=-73.5"]]


def signed_unauthorized(t, rng, ctx):
    params = rng.choice(UNAUTHORIZED)
    argv = ["--unsafe-bypass-gate"] + [x for p in params for x in ("--unsafe-param", p)]
    return t.run(*argv), 1, " ".join(params)


def plan_deviation(t, rng, ctx):
    kind = rng.choice(["skip2", "skip3", "skip4", "reorder34"])
    if kind.startswith("skip"):
        s = int(kind[-1])

        def dev(c, step, module, kw, orig):
            return {"receipt_hash": c.prev_hash} if step == s else None
        return t.run(deviation=dev), s, f"PR{s} skipped"
    held = {}

    def dev(c, step, module, kw, orig):
        if step == 3:
            held.update(module=module, kw=kw)
            return {"receipt_hash": c.prev_hash}
        if step == 4:
            r = orig(c, 4, module, **kw)
            held["kw"]["in_hash"] = c.last_out_hash        # a careful deviant agent keeps the data links consistent
            orig(c, 3, held["module"], **held["kw"])
            return r
        return None
    return t.run(deviation=dev), 3, "PR3 and PR4 reordered"


def window_gt_24h(t, rng, ctx):
    h = rng.randint(25, 48)
    return t.run("--unsafe-bypass-gate", "--window-hours", str(h)), 0, f"{h} h window"


# ---------------- insufficient evidence (validly signed) ----------------

def omitted_evidence(t, rng, ctx):
    kind = rng.choice(["raw_page", "raw_page", "decision_list", "db_readback", "reconciliation"])
    target = {"decision_list": 3, "db_readback": 4, "reconciliation": 5}.get(kind, 2)
    page = rng.randint(1, 3)

    def dev(c, step, module, kw, orig):
        if step == target:
            if kind == "raw_page":
                kw["evidence"] = [e for e in kw["evidence"] if not e["key"].endswith(f"page-{page:04d}.json")]
            else:
                kw["evidence"] = [e for e in kw["evidence"] if e["role"] != kind]
    return t.run(deviation=dev), None, f"{kind}{page if kind == 'raw_page' else ''} omitted"


def unreconcilable_counts(t, rng, ctx):
    kind = rng.choice(["pr4_inserted", "pr2_fetched", "pr3_accepted"])
    k = rng.randint(1, 20)

    def dev(c, step, module, kw, orig):
        p = kw.get("payload")
        if kind == "pr4_inserted" and step == 4:
            kw["payload"] = dict(p, inserted=p["inserted"] + k)
        elif kind == "pr2_fetched" and step == 2:
            kw["payload"] = dict(p, fetched=p["fetched"] + k)
        elif kind == "pr3_accepted" and step == 3:
            counts = dict(p["counts"], accepted=dict(p["counts"]["accepted"], new=p["counts"]["accepted"]["new"] + k))
            kw["payload"] = dict(p, counts=counts)
    return t.run(deviation=dev), None, f"{kind} +{k}"


def truncated(t, rng, ctx):
    s = rng.choice([3, 4, 5])

    def dev(c, step, module, kw, orig):
        if step == s:
            raise RuntimeError("process stopped")
    return t.run(deviation=dev), None, f"stopped before PR{s}"


SCENARIOS = [
    Scenario("clean_authorized_run", "legitimate", clean),
    Scenario("naive_artifact_tamper", "tampered", naive_tamper),
    Scenario("log_rewriting", "tampered", log_rewrite),
    Scenario("forward_recompute", "tampered", forward_recompute),
    Scenario("key_forgery", "tampered", key_forgery),
    Scenario("signed_but_unauthorized", "policy_violation", signed_unauthorized),
    Scenario("plan_deviation", "policy_violation", plan_deviation),
    Scenario("window_over_24h", "policy_violation", window_gt_24h),
    Scenario("omitted_evidence", "insufficient", omitted_evidence),
    Scenario("unreconcilable_counts", "insufficient", unreconcilable_counts),
    Scenario("truncated_trace", "insufficient", truncated),
    Scenario("replayed_receipt", "tampered", replay),
]
