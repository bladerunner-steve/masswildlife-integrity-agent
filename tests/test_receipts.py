"""Receipt schema and sign/verify tests for mwia.common.receipt. AI-assisted (Claude)."""
import copy
import uuid

import pytest

from mwia.common.canonical import ZERO_HASH, hash_obj
from mwia.common.receipt import validate_receipt_body, verify_signed_object
from mwia.notary.keys import keygen, load_active_private_key
from mwia.notary.service import Notary

from conftest import TEST_PASSPHRASE, make_body


@pytest.fixture
def body(notary):
    return make_body(notary.key_id, str(uuid.uuid4()), 0, ZERO_HASH, None)


def test_valid_body_roundtrips_unchanged(body):
    assert validate_receipt_body(body) == body
    assert len(body["nonce"]) == 32 and body["timestamp"].endswith("Z")


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(extra_field=1),                      # unknown field
    lambda b: b.update(step="0"),                           # type coercion is refused
    lambda b: b.update(step=6),                             # out of range
    lambda b: b.update(step_type="request"),                # step/type mismatch
    lambda b: b.update(spec_hash=ZERO_HASH),                # PR0 must have null spec_hash
    lambda b: b.update(prev_hash="A" * 64),                 # hex must be lower-case
    lambda b: b.update(timestamp="2026-11-23 10:00:00"),    # not RFC 3339 UTC
    lambda b: b.update(nonce="abc"),
    lambda b: b.update(notary_key_id="xyz"),
    lambda b: b.update(policy_decision="maybe"),
    lambda b: b["evidence"].append({"key": "k", "sha256": ZERO_HASH, "role": "bogus"}),
    lambda b: b.pop("payload"),
])
def test_invalid_bodies_rejected(body, mutate):
    b = copy.deepcopy(body)
    mutate(b)
    with pytest.raises(ValueError):
        validate_receipt_body(b)


def test_step_after_zero_requires_spec_hash(notary):
    with pytest.raises(ValueError):
        make_body(notary.key_id, str(uuid.uuid4()), 3, ZERO_HASH, None)


def test_sign_and_verify(notary, trusted, body):
    r = notary.sign_receipt(body)
    assert r["receipt_hash"] == hash_obj(body)
    assert len(r["signature"]) == 128
    assert verify_signed_object(r, trusted) == []


def test_tampered_body_detected(notary, trusted, body):
    r = notary.sign_receipt(body)
    t = copy.deepcopy(r)
    t["body"]["payload"]["step"] = 99
    assert verify_signed_object(t, trusted) == ["hash_mismatch", "bad_signature"]


def test_recomputed_hash_but_original_signature_detected(notary, trusted, body):
    r = notary.sign_receipt(body)
    t = copy.deepcopy(r)
    t["body"]["out_hash"] = ZERO_HASH
    t["receipt_hash"] = hash_obj(t["body"])  # log-rewriting attacker fixes the hash, can't fix the signature
    assert verify_signed_object(t, trusted) == ["bad_signature"]


def test_tampered_hash_field_detected(notary, trusted, body):
    r = notary.sign_receipt(body)
    t = dict(r, receipt_hash=ZERO_HASH)
    assert verify_signed_object(t, trusted) == ["hash_mismatch"]


def test_untrusted_key_detected(tmp_path, trusted, body):
    other_dir = tmp_path / "other"
    keygen(other_dir, TEST_PASSPHRASE)
    key, kid = load_active_private_key(other_dir, TEST_PASSPHRASE)
    forged = Notary(key, kid).sign_receipt(dict(body, notary_key_id=kid))
    assert verify_signed_object(forged, trusted) == ["untrusted_key"]


def test_forged_signature_claiming_trusted_key_id(tmp_path, notary, trusted, body):
    other_dir = tmp_path / "other"
    keygen(other_dir, TEST_PASSPHRASE)
    key, _ = load_active_private_key(other_dir, TEST_PASSPHRASE)
    from mwia.common.canonical import jcs
    forged = {"body": body, "receipt_hash": hash_obj(body), "signature": key.sign(jcs(body)).hex()}
    assert verify_signed_object(forged, trusted) == ["bad_signature"]


@pytest.mark.parametrize("obj", [{}, {"body": "x", "receipt_hash": "y", "signature": "z"},
                                 {"body": {}, "receipt_hash": 1, "signature": "z"}])
def test_malformed_objects(trusted, obj):
    assert verify_signed_object(obj, trusted) == ["malformed"]


def test_non_hex_signature(notary, trusted, body):
    r = notary.sign_receipt(body)
    assert verify_signed_object(dict(r, signature="zz"), trusted) == ["bad_signature"]
