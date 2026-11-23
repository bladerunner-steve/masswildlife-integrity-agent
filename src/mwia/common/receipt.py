"""Receipt and seal bodies: schema, construction and signature/hash verification.

A receipt object is {body, receipt_hash, signature}, where receipt_hash = SHA-256(JCS(body)) and
signature = Ed25519(JCS(body)), hex-encoded. A run seal is {body, seal_hash, signature} with a seal/v1 body.
Bodies are validated strictly (no extra fields, no type coercion), so the signed bytes always equal what
was submitted. The extension field `payload` carries step-specific data (PR0 plan, PR4 DB facts, ...).
Spec deviation: PR0's spec_hash is null, because PR0 cannot contain its own hash. Steps 1-5 carry PR0's
receipt_hash.
AI-assisted (Claude). Verified by: tests/test_receipts.py (schema, sign/verify, tamper detection) and
tests/test_chain.py.
"""
from __future__ import annotations

import json
import secrets
from typing import Annotated, Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .canonical import hash_obj, jcs
from .timeutil import RFC3339_UTC, utc_now

STEP_TYPES: dict[int, str] = {
    0: "plan", 1: "request", 2: "response", 3: "filtering", 4: "db_update", 5: "completion",
}
EVIDENCE_ROLES = ("input", "output", "raw_response", "decision_list", "db_readback", "reconciliation",
                  "plan", "request", "policy")

Hex64 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Hex32 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
KeyId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
Uuid = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
Timestamp = Annotated[str, StringConstraints(pattern=RFC3339_UTC.pattern)]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: Annotated[str, StringConstraints(min_length=1)]
    sha256: Hex64
    role: Literal[EVIDENCE_ROLES]  # type: ignore[valid-type]


class ReceiptBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    schema_: Literal["receipt/v1"] = Field(alias="schema")
    run_id: Uuid
    step: Annotated[int, Field(ge=0, le=5)]
    step_type: Literal["plan", "request", "response", "filtering", "db_update", "completion"]
    module: Annotated[str, StringConstraints(min_length=1)]
    model_id: Annotated[str, StringConstraints(min_length=1)]
    agent_id: Hex64
    in_hash: Hex64
    out_hash: Hex64
    evidence: list[Evidence]
    spec_hash: Hex64 | None
    prev_hash: Hex64
    policy_decision: Literal["pass", "violation", "n/a"]
    policy_rules_evaluated: list[str]
    payload: dict[str, Any]
    nonce: Hex32
    timestamp: Timestamp
    notary_key_id: KeyId

    @model_validator(mode="after")
    def _step_consistency(self) -> "ReceiptBody":
        if STEP_TYPES[self.step] != self.step_type:
            raise ValueError(f"step {self.step} must have step_type {STEP_TYPES[self.step]!r}")
        if (self.step == 0) != (self.spec_hash is None):
            raise ValueError("spec_hash must be null for PR0 and set for steps 1-5")
        return self


class SealBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    schema_: Literal["seal/v1"] = Field(alias="schema")
    run_id: Uuid
    merkle_root: Hex64
    receipt_count: Annotated[int, Field(ge=1)]
    head_hash: Hex64
    prev_seal_hash: Hex64
    nonce: Hex32
    timestamp: Timestamp
    notary_key_id: KeyId


def _validate(model: type[BaseModel], body: dict) -> dict:
    # Validate through JSON so the result is exactly the JSON data model (and must be JSON-serializable).
    m = model.model_validate_json(json.dumps(body), strict=True)
    out = m.model_dump(mode="json", by_alias=True)
    if jcs(out) != jcs(body):  # defence in depth: validation must never alter the signed content
        raise ValueError("body changed during validation")
    return out


def validate_receipt_body(body: dict) -> dict:
    return _validate(ReceiptBody, body)


def validate_seal_body(body: dict) -> dict:
    return _validate(SealBody, body)


def new_nonce() -> str:
    return secrets.token_hex(16)


def new_receipt_body(*, run_id: str, step: int, module: str, model_id: str, agent_id: str, in_hash: str,
                     out_hash: str, evidence: list[dict], spec_hash: str | None, prev_hash: str,
                     policy_decision: str, policy_rules_evaluated: list[str], notary_key_id: str,
                     payload: dict | None = None) -> dict:
    """Build an unsigned receipt body with a fresh nonce and timestamp."""
    body = {
        "schema": "receipt/v1", "run_id": run_id, "step": step, "step_type": STEP_TYPES[step],
        "module": module, "model_id": model_id, "agent_id": agent_id, "in_hash": in_hash, "out_hash": out_hash,
        "evidence": evidence, "spec_hash": spec_hash, "prev_hash": prev_hash, "policy_decision": policy_decision,
        "policy_rules_evaluated": policy_rules_evaluated, "payload": payload or {}, "nonce": new_nonce(),
        "timestamp": utc_now(), "notary_key_id": notary_key_id,
    }
    return validate_receipt_body(body)


def body_hash(body: dict) -> str:
    return hash_obj(body)


def verify_signed_object(obj: dict, trusted: dict[str, Ed25519PublicKey]) -> list[str]:
    """Check a receipt or seal object against trusted keys. Returns problem codes (empty list = valid).

    Codes: malformed, untrusted_key, hash_mismatch, bad_signature.
    """
    hash_field = "seal_hash" if "seal_hash" in obj else "receipt_hash"
    body = obj.get("body")
    if not isinstance(body, dict) or not isinstance(obj.get(hash_field), str) or not isinstance(obj.get("signature"), str):
        return ["malformed"]
    problems: list[str] = []
    try:
        recomputed = hash_obj(body)
    except Exception:
        return ["malformed"]
    if recomputed != obj[hash_field]:
        problems.append("hash_mismatch")
    key = trusted.get(body.get("notary_key_id", ""))
    if key is None:
        problems.append("untrusted_key")
        return problems
    try:
        key.verify(bytes.fromhex(obj["signature"]), jcs(body))
    except (InvalidSignature, ValueError):
        problems.append("bad_signature")
    return problems
