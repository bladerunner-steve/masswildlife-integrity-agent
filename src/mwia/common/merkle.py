"""Binary Merkle tree over a run's receipt hashes, as specified in RFC 6962 section 2.1 / RFC 9162 section 2.1.

Leaf hash = SHA-256(0x00 || leaf), node hash = SHA-256(0x01 || left || right). The 0x00/0x01 prefixes separate
leaves from interior nodes, so an interior node can't be passed off as a leaf. Unbalanced trees split at the
largest power of two below n, which gives every leaf an inclusion proof. Leaves here are the raw 32 bytes of
each receipt_hash, in chain order.
AI-assisted (Claude). Verified by: tests/test_merkle.py (RFC 6962 test vectors from the Certificate
Transparency reference implementation, and inclusion proofs for every index of trees with 1-33 leaves).
"""
from __future__ import annotations

import hashlib


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def leaf_hash(leaf: bytes) -> bytes:
    return _h(b"\x00" + leaf)


def node_hash(left: bytes, right: bytes) -> bytes:
    return _h(b"\x01" + left + right)


def _split(n: int) -> int:
    """Largest power of two strictly less than n (n >= 2)."""
    k = 1
    while k << 1 < n:
        k <<= 1
    return k


def root(leaves: list[bytes]) -> bytes:
    n = len(leaves)
    if n == 0:
        return _h(b"")
    if n == 1:
        return leaf_hash(leaves[0])
    k = _split(n)
    return node_hash(root(leaves[:k]), root(leaves[k:]))


def inclusion_proof(leaves: list[bytes], index: int) -> list[bytes]:
    """Audit path for leaves[index] (RFC 6962 PATH(m, D[n]))."""
    n = len(leaves)
    if not 0 <= index < n:
        raise IndexError(index)
    if n == 1:
        return []
    k = _split(n)
    if index < k:
        return inclusion_proof(leaves[:k], index) + [root(leaves[k:])]
    return inclusion_proof(leaves[k:], index - k) + [root(leaves[:k])]


def verify_inclusion(leaf: bytes, index: int, size: int, proof: list[bytes], expected_root: bytes) -> bool:
    """RFC 9162 section 2.1.3.2 inclusion proof verification."""
    if not 0 <= index < size:
        return False
    fn, sn = index, size - 1
    r = leaf_hash(leaf)
    for p in proof:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = node_hash(p, r)
            if not fn & 1:
                while True:
                    fn >>= 1
                    sn >>= 1
                    if fn & 1 or fn == 0:
                        break
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == expected_root


def root_hex(receipt_hashes: list[str]) -> str:
    """Merkle root (hex) over receipt hashes given as hex strings, in chain order."""
    return root([bytes.fromhex(h) for h in receipt_hashes]).hex()
