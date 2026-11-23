"""Verifier findings: one problem found by one layer, with a severity and a plain-language message.

severity "fail" -> VERIFICATION FAILED; severity "insufficient" -> INSUFFICIENT EVIDENCE (only if nothing failed).
Messages are written for a non-cryptographer reading the badge page.
AI-assisted (Claude). Verified by: tests/test_verify.py.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

MESSAGES = {
    # Layer A: cryptographic
    "object_unreadable": "A stored record could not be read.",
    "receipt_malformed": "A receipt is damaged or not in the expected format.",
    "receipt_schema": "A receipt does not follow the receipt format.",
    "receipt_hash_mismatch": "A receipt's content no longer matches its fingerprint: it was changed after it was written.",
    "bad_signature": "A receipt's signature does not match its content: it was altered or forged.",
    "untrusted_key": "A receipt was signed by a key that is not one of the trusted notary keys.",
    "key_retired": "A receipt was signed with a notary key after that key was retired.",
    "receipt_misplaced": "A receipt is stored under the wrong run or step (it may have been copied from another run).",
    "pr0_missing": "The run's signed plan (step 0) is missing.",
    "multiple_pr0": "The run has more than one signed plan.",
    "chain_fork": "Two receipts claim the same predecessor: the record of steps was forked.",
    "chain_break": "The chain of receipts is broken: a step's link to the previous step does not match.",
    "spec_hash_mismatch": "A receipt points to a different plan than the run's signed plan.",
    "prev_seal_mismatch": "The run does not link to the previous run's seal: runs may have been removed or reordered.",
    "nonce_reused": "A receipt reuses a one-time value from another receipt (a replay).",
    "replayed_receipt": "A receipt from another run was inserted into this run.",
    "evidence_missing": "A piece of evidence that a receipt refers to is no longer in the vault.",
    "evidence_hash_mismatch": "A piece of stored evidence was changed after its receipt was signed.",
    "out_hash_mismatch": "A step's recorded output does not match the stored evidence for that output.",
    "in_hash_mismatch": "A step did not take the previous step's output as its input.",
    "measurement_mismatch": "A module's code fingerprint differs from the one declared in the signed plan.",
    "seal_missing": "The run was never sealed, so its record may be incomplete (truncated trace).",
    "seal_invalid": "The run's seal is damaged, altered or not signed by a trusted key.",
    "merkle_root_mismatch": "The run's seal does not cover exactly the receipts in the vault.",
    "seal_inconsistent": "The run's seal disagrees with its receipts (count, last receipt or previous seal).",
    "vault_ledger": "The vault's tamper-evident ledger shows that objects of this run were changed, removed or added.",
    "vault_ledger_global": "The vault's tamper-evident ledger itself has been altered.",
    "anchor_mismatch": "The vault no longer matches the externally recorded anchors (rollback, deletion or rewrite).",
    "seal_not_anchored": "The run's seal was not recorded in the external anchor log.",
    # Layer B: policy
    "policy_snapshot_inconsistent": "The policy stored with the run does not match the policy its plan signed.",
    "policy_weaker_than_pins": "The run's signed policy differs from the trusted, pinned values (project, place, limits).",
    "request_forbidden_param": "The request used a location or scope parameter that the policy forbids.",
    "request_wrong_project": "The request asked for a different iNaturalist project.",
    "request_wrong_target": "The request went to a host, endpoint or method that the policy does not allow.",
    "request_unknown_param": "The request used a parameter that the policy does not allow.",
    "request_forbidden_field": "The request asked for private (true) coordinates.",
    "request_window": "The request's time window differs from the plan or exceeds 24 hours plus grace.",
    "request_order": "The request did not use the required ordering (by id, ascending).",
    "page_url_mismatch": "A fetched page's actual URL differs from the parameters recorded for it.",
    "window_too_long": "The run's planned time window is longer than 24 hours plus grace.",
    "agent_recorded_violation": "The agent itself recorded a policy violation (for example, a blocked request).",
    "db_user": "The database update ran as a user other than the least-privilege account.",
    "db_target": "The database update targeted a table the policy does not allow.",
    "db_operations": "The database update used SQL operations the policy does not allow.",
    "dry_run_violated": "A dry run wrote to the database.",
    "plan_deviation": "The steps actually executed differ from the signed plan (skipped, reordered or extra steps).",
    "out_of_scope_written": "An observation outside the project's place reached the database.",
    "out_of_scope_accepted": "An observation outside the project's place was accepted.",
    "outside_window_accepted": "An observation created outside the run's time window was accepted.",
    "unaccepted_record_written": "A record that was not accepted by the filter reached the database.",
    # Layer C: evidence
    "steps_missing": "Some steps of the run left no receipt, so their evidence can't be checked.",
    "mandatory_evidence_missing": "A required piece of evidence was never recorded.",
    "raw_page_missing": "A fetched page of results was not kept as evidence.",
    "raw_page_inconsistent": "A stored page of results does not match what was recorded about it.",
    "pagination_incomplete": "The pages of results do not form a complete, gap-free sequence.",
    "pages_incomplete": "Not every page of results was fetched.",
    "counts_unreconciled": "The record counts do not add up across the steps.",
    "readback_incomplete": "The database readback does not contain every accepted record.",
    "readback_mismatch": "The database readback does not match what was written.",
    "stale_response": "A response was fetched too long after (or before) the run's time window.",
    "stale_observation": "An accepted observation's timestamp is outside the run's time window.",
    "completion_inconsistent": "The run's completion decision does not follow from its evidence.",
}


@dataclass
class Finding:
    layer: str          # A | B | C
    code: str
    severity: str       # fail | insufficient
    detail: str = ""
    step: int | None = None
    module: str | None = None

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, self.code)

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if v is not None and v != ""}
        d["message"] = self.message
        return d
