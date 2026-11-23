"""Canonical JSON (RFC 8785 JCS) and SHA-256 helpers.

receipt_hash = SHA-256(JCS(body)). JCS sorts keys by UTF-16 code units, removes whitespace, and serializes
numbers in ECMAScript form. rfc8785 rejects integers outside +/-(2^53 - 1), so receipts never carry such values.
AI-assisted (Claude). Verified by: tests/test_canonical.py (golden vector, key-order and Unicode stability).
"""
from __future__ import annotations

import hashlib
from typing import Any

import rfc8785

ZERO_HASH = "0" * 64  # prev_hash of the very first run's PR0


def jcs(obj: Any) -> bytes:
    """Return the RFC 8785 canonical serialization of a JSON-compatible object."""
    return rfc8785.dumps(obj)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_obj(obj: Any) -> str:
    """SHA-256 hex of the canonical form of obj."""
    return sha256_hex(jcs(obj))
