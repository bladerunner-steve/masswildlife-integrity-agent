"""Chain building and sealing tests for mwia.notary.service (in-process notary). AI-assisted (Claude)."""
import uuid

import pytest

from mwia.common import merkle
from mwia.common.canonical import ZERO_HASH
from mwia.common.receipt import verify_signed_object
from mwia.notary.service import NotaryRefusal

from conftest import build_chain, make_body


def test_full_chain_links(notary, trusted):
    rs = build_chain(notary, notary.key_id)
    assert [r["body"]["step"] for r in rs] == [0, 1, 2, 3, 4, 5]
    assert rs[0]["body"]["prev_hash"] == ZERO_HASH and rs[0]["body"]["spec_hash"] is None
    for prev, cur in zip(rs, rs[1:]):
        assert cur["body"]["prev_hash"] == prev["receipt_hash"]
        assert cur["body"]["spec_hash"] == rs[0]["receipt_hash"]
    assert len({r["body"]["nonce"] for r in rs}) == 6
    assert all(verify_signed_object(r, trusted) == [] for r in rs)


def test_seal_commits_to_every_receipt(notary, trusted):
    rs = build_chain(notary, notary.key_id)
    seal = notary.seal_run(rs[0]["body"]["run_id"])
    b = seal["body"]
    hashes = [r["receipt_hash"] for r in rs]
    assert verify_signed_object(seal, trusted) == []
    assert b["receipt_count"] == 6 and b["head_hash"] == hashes[-1] and b["prev_seal_hash"] == ZERO_HASH
    assert b["merkle_root"] == merkle.root_hex(hashes)
    leaves = [bytes.fromhex(h) for h in hashes]
    root = bytes.fromhex(b["merkle_root"])
    for i, leaf in enumerate(leaves):
        assert merkle.verify_inclusion(leaf, i, 6, merkle.inclusion_proof(leaves, i), root)
    # a receipt from another run is not in this tree
    other = build_chain(notary, notary.key_id)[2]
    assert not merkle.verify_inclusion(bytes.fromhex(other["receipt_hash"]), 2, 6,
                                       merkle.inclusion_proof(leaves, 2), root)


def test_runs_chain_through_seals(notary):
    r1 = build_chain(notary, notary.key_id)
    s1 = notary.seal_run(r1[0]["body"]["run_id"])
    r2 = build_chain(notary, notary.key_id, prev_seal=s1["seal_hash"])
    s2 = notary.seal_run(r2[0]["body"]["run_id"])
    assert r2[0]["body"]["prev_hash"] == s1["seal_hash"]
    assert s2["body"]["prev_seal_hash"] == s1["seal_hash"]


def test_first_receipt_must_be_pr0(notary):
    with pytest.raises(NotaryRefusal, match="must be PR0"):
        notary.sign_receipt(make_body(notary.key_id, str(uuid.uuid4()), 1, ZERO_HASH, ZERO_HASH))


def test_fork_refused(notary):
    rs = build_chain(notary, notary.key_id, steps=[0, 1])
    rid, spec = rs[0]["body"]["run_id"], rs[0]["receipt_hash"]
    with pytest.raises(NotaryRefusal, match="does not extend"):
        notary.sign_receipt(make_body(notary.key_id, rid, 2, rs[0]["receipt_hash"], spec))  # skips PR1's hash


def test_second_pr0_refused(notary):
    rs = build_chain(notary, notary.key_id, steps=[0])
    with pytest.raises(NotaryRefusal, match="already has a PR0"):
        notary.sign_receipt(make_body(notary.key_id, rs[0]["body"]["run_id"], 0, rs[0]["receipt_hash"], None))


def test_seal_rules(notary):
    rs = build_chain(notary, notary.key_id, steps=[0, 1, 2])
    rid = rs[0]["body"]["run_id"]
    with pytest.raises(NotaryRefusal, match="after its PR5"):
        notary.seal_run(rid)
    with pytest.raises(NotaryRefusal, match="unknown run"):
        notary.seal_run(str(uuid.uuid4()))
    full = build_chain(notary, notary.key_id)
    fid = full[0]["body"]["run_id"]
    notary.seal_run(fid)
    with pytest.raises(NotaryRefusal, match="already sealed"):
        notary.seal_run(fid)
    with pytest.raises(NotaryRefusal, match="already sealed"):
        notary.sign_receipt(make_body(notary.key_id, fid, 5, full[-1]["receipt_hash"], full[0]["receipt_hash"]))


def test_wrong_key_id_and_invalid_schema_refused(notary):
    with pytest.raises(NotaryRefusal, match="active key"):
        notary.sign_receipt(make_body("0" * 16, str(uuid.uuid4()), 0, ZERO_HASH, None))
    b = make_body(notary.key_id, str(uuid.uuid4()), 0, ZERO_HASH, None)
    b["unexpected"] = True
    with pytest.raises(NotaryRefusal, match="invalid receipt body"):
        notary.sign_receipt(b)


def test_notary_does_not_enforce_plan_conformance(notary, trusted):
    """By design: a skipped step is still validly signed, so layer B (policy) has something to catch."""
    rs = build_chain(notary, notary.key_id, steps=[0, 1, 3, 4, 5])
    seal = notary.seal_run(rs[0]["body"]["run_id"])
    assert seal["body"]["receipt_count"] == 5
    assert verify_signed_object(seal, trusted) == []
