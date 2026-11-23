"""RunContext: shared state of one run, plus receipt emission (evidence -> vault, body -> notary, receipt ->
vault -> provenance index).

Conventions every module follows (the verifier relies on them):
- out_hash = SHA-256(JCS(primary output object)), which is also that evidence object's sha256;
- in_hash = out_hash of the previously emitted receipt (PR0: hash of its declared inputs);
- agent_id is measured from the files on disk at emit time, so a code change mid-run shows up as a mismatch
  against PR0's expected_measurements.
AI-assisted (Claude). Verified by: tests/test_pipeline.py (chain, evidence and measurement consistency).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from mwia.common.canonical import hash_obj, sha256_hex
from mwia.common.measure import module_measurements
from mwia.common.receipt import new_receipt_body
from mwia.index.provenance import store_and_index
from mwia.vault import evidence_key, receipt_key, seal_key
from mwia.vault.anchor import SEAL_SUFFIX

from .config import Config


def latest_seal_hash(vault) -> str | None:
    seals = [k for k in vault.list_keys() if k.endswith(SEAL_SUFFIX)]
    return json.loads(vault.get(seals[-1]))["seal_hash"] if seals else None


@dataclass
class RunContext:
    cfg: Config
    run_id: str
    run_date: str
    vault_env: str
    db_env: str
    dry_run: bool
    vault: object
    notary: object
    index_db: object | None          # GuardedConnection for provenance_index, or None (dry run)
    prev_hash: str
    spec_hash: str | None = None
    last_out_hash: str | None = None
    receipts: list[dict] = field(default_factory=list)
    receipt_keys: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    @property
    def key_id(self) -> str:
        return self.notary.key_id

    def measure(self) -> dict[str, str]:
        return module_measurements(self.cfg.root, self.cfg.manifest_path, self.cfg.policy_path, self.key_id)

    def model_id(self, module: str) -> str:
        return self.cfg.manifest["modules"][module]["model_id"]

    def put_evidence_json(self, name: str, obj, role: str) -> dict:
        info = self.vault.put_json(evidence_key(self.run_date, self.run_id, name), obj)
        return {"key": info.key, "sha256": info.sha256, "role": role}

    def put_evidence_bytes(self, name: str, data: bytes, role: str) -> dict:
        info = self.vault.put(evidence_key(self.run_date, self.run_id, name), data)
        return {"key": info.key, "sha256": info.sha256, "role": role}

    def emit(self, step: int, module: str, *, in_hash: str, out_hash: str, evidence: list[dict],
             policy_decision: str = "n/a", rules: list[str] | None = None, payload: dict | None = None) -> dict:
        body = new_receipt_body(
            run_id=self.run_id, step=step, module=module, model_id=self.model_id(module),
            agent_id=self.measure()[module], in_hash=in_hash, out_hash=out_hash, evidence=evidence,
            spec_hash=self.spec_hash, prev_hash=self.prev_hash, policy_decision=policy_decision,
            policy_rules_evaluated=rules or [], notary_key_id=self.key_id, payload=payload or {})
        receipt = self.notary.sign_receipt(body)
        key = receipt_key(self.run_date, self.run_id, step, body["step_type"])
        store_and_index(self.vault, self.index_db, self.vault_env, key, receipt)
        self.receipts.append(receipt)
        self.receipt_keys.append(key)
        self.prev_hash = receipt["receipt_hash"]
        self.last_out_hash = out_hash
        if step == 0:
            self.spec_hash = receipt["receipt_hash"]
        self.log.append(f"PR{step} {module} {receipt['receipt_hash'][:16]} policy={policy_decision}")
        return receipt

    def seal(self) -> tuple[dict, str]:
        seal = self.notary.seal_run(self.run_id)
        key = seal_key(self.run_date, self.run_id)
        store_and_index(self.vault, self.index_db, self.vault_env, key, seal)
        return seal, key


def out_of(obj) -> str:
    return hash_obj(obj)


def bytes_hash(data: bytes) -> str:
    return sha256_hex(data)
