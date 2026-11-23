"""Layer A: cryptographic receipt verification.

Checks: every receipt and the seal verify against a trusted key (and the key was not retired before the
signature); receipt_hash recomputes; receipts sit under their own run and step; the prev_hash links form one
unbroken chain from PR0; PR0.prev_hash is the previous run's seal; spec_hash = PR0's hash; nonces and
receipt hashes are unique across the vault (no replay); every referenced evidence object exists and
re-hashes to its recorded hash; out_hash equals the step's primary output evidence and in_hash equals the
previous step's out_hash; each module's agent_id equals PR0's expected measurement; the seal's Merkle root,
count, head and prev_seal_hash match; the vault ledger is intact for this run; and the external anchors agree.
Produces the chain (receipts in chain order) used by layers B and C.
AI-assisted (Claude). Verified by: tests/test_verify.py (one tamper case per check).
"""
from __future__ import annotations

from mwia.common import merkle
from mwia.common.canonical import sha256_hex
from mwia.common.receipt import validate_receipt_body, validate_seal_body, verify_signed_object
from mwia.common.timeutil import parse_utc

from .findings import Finding

PRIMARY_ROLE = {"plan": "plan", "request": "request", "response": "output", "filtering": "decision_list",
                "db_update": "db_readback", "completion": "reconciliation"}
GLOBAL_LEDGER = {"ledger_malformed", "ledger_noncanonical", "ledger_seq_gap", "ledger_chain_break",
                 "ledger_duplicate_put", "ledger_bad_mode", "ledger_unknown_key", "ledger_hash_conflict",
                 "retention_shortened"}
ANCHOR_FAIL = {"anchor_mismatch", "anchored_seal_missing", "ledger_truncated", "ledger_rewritten"}


def _f(code, detail="", step=None, module=None, severity="fail"):
    return Finding("A", code, severity, detail, step, module)


def check(run, vctx) -> tuple[list[Finding], list[dict]]:
    out: list[Finding] = []
    prefix = f"runs/{run.run_date}/{run.run_id}/"
    for key in run.unreadable:
        out.append(_f("object_unreadable", key))
    # --- individual receipts
    receipts = []
    for key, obj in run.receipt_keys.items():
        if obj is None:
            continue
        body = obj.get("body") if isinstance(obj, dict) else None
        step = body.get("step") if isinstance(body, dict) else None
        mod = body.get("module") if isinstance(body, dict) else None
        codes = verify_signed_object(obj, vctx.trusted)
        for c in codes:
            out.append(_f({"malformed": "receipt_malformed", "hash_mismatch": "receipt_hash_mismatch",
                           "bad_signature": "bad_signature", "untrusted_key": "untrusted_key"}[c], key, step, mod))
        if "malformed" in codes:
            continue
        try:
            validate_receipt_body(body)
        except ValueError as e:
            out.append(_f("receipt_schema", f"{key}: {str(e).splitlines()[0]}", step, mod))
            continue
        retired = vctx.retired_at.get(body["notary_key_id"])
        if retired and parse_utc(body["timestamp"]) > retired:
            out.append(_f("key_retired", key, step, mod))
        if body["run_id"] != run.run_id or key != f"{prefix}{body['step']}-{body['step_type']}.json":
            out.append(_f("receipt_misplaced", key, step, mod))
        # replay: the same receipt (or its one-time nonce) also appears under another run
        other = (vctx.nonce_owner.get(body["nonce"], set()) | vctx.hash_owner.get(obj["receipt_hash"], set())) \
            - {run.run_id}
        if other:
            out.append(_f("replayed_receipt", f"also in run {sorted(other)[0]}", step, mod))
        receipts.append(obj)
    # --- chain reconstruction
    pr0s = [r for r in receipts if r["body"]["step"] == 0]
    chain: list[dict] = []
    if not pr0s:
        out.append(_f("pr0_missing", step=0, module="M0:plan"))
    else:
        if len(pr0s) > 1:
            out.append(_f("multiple_pr0", step=0, module="M0:plan"))
        pr0 = pr0s[0]
        by_prev: dict[str, list[dict]] = {}
        for r in receipts:
            if r is not pr0:
                by_prev.setdefault(r["body"]["prev_hash"], []).append(r)
        chain = [pr0]
        while True:
            nxt = by_prev.get(chain[-1]["receipt_hash"], [])
            if len(nxt) > 1:
                out.append(_f("chain_fork", step=nxt[0]["body"]["step"], module=nxt[0]["body"]["module"]))
            if not nxt or nxt[0] in chain:
                break
            chain.append(nxt[0])
        for r in receipts:
            if r not in chain:
                out.append(_f("chain_break", f"receipt for step {r['body']['step']} is not linked into the chain",
                              r["body"]["step"], r["body"]["module"]))
        # PR0 links to the previous run's seal
        expected_prev = vctx.previous_seal_hash(run)
        if pr0["body"]["prev_hash"] != expected_prev:
            out.append(_f("prev_seal_mismatch", f"expected {expected_prev[:16]}", 0, "M0:plan"))
        plan = pr0["body"]["payload"]
        expected = plan.get("expected_measurements", {}) if isinstance(plan, dict) else {}
        prev = None
        for r in chain:
            b = r["body"]
            if b["step"] != 0 and b["spec_hash"] != pr0["receipt_hash"]:
                out.append(_f("spec_hash_mismatch", step=b["step"], module=b["module"]))
            if expected.get(b["module"]) != b["agent_id"]:
                out.append(_f("measurement_mismatch", b["module"], b["step"], b["module"]))
            for ev in b["evidence"]:
                data = vctx.vault._read(ev["key"])
                if data is None:
                    out.append(_f("evidence_missing", ev["key"], b["step"], b["module"]))
                elif sha256_hex(data) != ev["sha256"]:
                    out.append(_f("evidence_hash_mismatch", ev["key"], b["step"], b["module"]))
            primary = [e for e in b["evidence"] if e["role"] == PRIMARY_ROLE[b["step_type"]]]
            if primary and primary[-1]["sha256"] != b["out_hash"]:
                out.append(_f("out_hash_mismatch", step=b["step"], module=b["module"]))
            if prev is not None and b["in_hash"] != prev["body"]["out_hash"]:
                out.append(_f("in_hash_mismatch", step=b["step"], module=b["module"]))
            prev = r
        nonces = [r["body"]["nonce"] for r in chain]
        if len(set(nonces)) != len(nonces):
            out.append(_f("nonce_reused", "within this run"))
    # --- seal
    seal = run.seal
    if seal is None:
        out.append(_f("seal_missing", severity=vctx.truncated_severity))
    else:
        codes = verify_signed_object(seal, vctx.trusted)
        try:
            validate_seal_body(seal.get("body"))
        except (ValueError, TypeError):
            codes = codes + ["schema"]
        if codes:
            out.append(_f("seal_invalid", ", ".join(codes)))
        elif chain:
            sb = seal["body"]
            hashes = [r["receipt_hash"] for r in chain]
            if sb["run_id"] != run.run_id:
                out.append(_f("seal_inconsistent", "seal belongs to another run"))
            if sb["merkle_root"] != merkle.root_hex(hashes):
                out.append(_f("merkle_root_mismatch", f"{len(hashes)} receipts in chain, seal covers "
                                                      f"{sb['receipt_count']}"))
            if sb["receipt_count"] != len(hashes) or sb["head_hash"] != hashes[-1] \
                    or sb["prev_seal_hash"] != chain[0]["body"]["prev_hash"]:
                out.append(_f("seal_inconsistent"))
            if vctx.anchored_seals is not None and seal.get("seal_hash") not in vctx.anchored_seals:
                out.append(_f("seal_not_anchored", severity="insufficient"))
    # --- vault ledger and anchors
    for p in vctx.ledger_problems:
        if p.code in GLOBAL_LEDGER:
            out.append(_f("vault_ledger_global", f"{p.code} at ledger line {p.seq}"))
        elif p.key and p.key.startswith(prefix):
            out.append(_f("vault_ledger", f"{p.code}: {p.key}", _step_of(p.key)))
    for p in vctx.anchor_problems:
        if p.code in ANCHOR_FAIL:
            out.append(_f("anchor_mismatch", f"{p.code}: {p.detail}"))
    return out, chain


def _step_of(key: str) -> int | None:
    name = key.rsplit("/", 1)[-1]
    return int(name.split("-", 1)[0]) if name[:1].isdigit() else None
