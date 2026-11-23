"""Canonicalization stability tests for mwia.common.canonical (RFC 8785 JCS).

Golden vectors are written by hand from the RFC 8785 rules (and its section 3.2.2 number example), not
produced by the code under test. AI-assisted (Claude).
"""
import hashlib
import random

import pytest
import rfc8785

from mwia.common.canonical import hash_obj, jcs


def test_rfc8785_number_example():
    # RFC 8785 section 3.2.2 example input and its canonical number forms
    obj = {"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001]}
    assert jcs(obj) == b'{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}'


def test_key_order_and_unicode_golden():
    obj = {"€": "x", "b": 2, "a": {"z": "é", "y": [3, 1.5, True, None]}}
    expected = '{"a":{"y":[3,1.5,true,null],"z":"é"},"b":2,"€":"x"}'.encode("utf-8")
    assert jcs(obj) == expected
    assert hash_obj(obj) == hashlib.sha256(expected).hexdigest()


def test_hash_independent_of_insertion_order():
    base = {f"k{i}": {"v": i, "list": [i, str(i)], "nested": {"b": i, "a": -i}} for i in range(25)}
    h = hash_obj(base)
    rng = random.Random(7)
    for _ in range(50):
        items = list(base.items())
        rng.shuffle(items)
        assert hash_obj(dict(items)) == h


def test_array_order_is_significant():
    assert hash_obj([1, 2]) != hash_obj([2, 1])


def test_large_integers_rejected():
    jcs({"id": 2**53 - 1})  # largest safe integer is fine
    with pytest.raises(rfc8785.IntegerDomainError):
        jcs({"id": 2**53 + 1})


def test_nan_rejected():
    with pytest.raises(rfc8785.FloatDomainError):
        jcs({"x": float("nan")})
