"""Merkle root and inclusion-proof tests for mwia.common.merkle (RFC 6962 / RFC 9162).

Root vectors are the RFC 6962 test data used by the Certificate Transparency reference implementation
(8 leaves: "", 00, 10, 2021, 3031, 40414243, 5051..57, 6061..6f), for tree sizes 1 to 8. AI-assisted (Claude).
"""
import hashlib

import pytest

from mwia.common import merkle

CT_LEAVES = [bytes.fromhex(h) for h in [
    "", "00", "10", "2021", "3031", "40414243", "5051525354555657", "606162636465666768696a6b6c6d6e6f"]]
CT_ROOTS = [
    "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "fac54203e7cc696cf0dfcb42c92a1d9dbaf70ad9e621f4bd8d98662f00e3c125",
    "aeb6bcfe274b70a14fb067a5e5578264db0fa9b51af5e0ba159158f329e06e77",
    "d37ee418976dd95753c1c73862b9398fa2a2cf9b4ff0fdfe8b30cd95209614b7",
    "4e3bbb1f7b478dcfe71fb631631519a3bca12c9aefca1612bfce4c13a86264d4",
    "76e67dadbcdf1e10e1b74ddc608abd2f98dfb16fbce75277b5232a127f2087ef",
    "ddb89be403809e325750d3d263cd78929c2942b7942a34b77e122c9594a74c8c",
    "5dc9da79a70659a9ad559cb701ded9a2ab9d823aad2f4960cfe370eff4604328",
]


@pytest.mark.parametrize("n", range(1, 9))
def test_rfc6962_roots(n):
    assert merkle.root(CT_LEAVES[:n]).hex() == CT_ROOTS[n - 1]


def test_empty_tree():
    assert merkle.root([]) == hashlib.sha256(b"").digest()


def _leaves(n):
    return [hashlib.sha256(str(i).encode()).digest() for i in range(n)]


@pytest.mark.parametrize("n", range(1, 34))
def test_inclusion_proofs_every_index(n):
    leaves = _leaves(n)
    r = merkle.root(leaves)
    for i in range(n):
        proof = merkle.inclusion_proof(leaves, i)
        assert merkle.verify_inclusion(leaves[i], i, n, proof, r)
        bigger = merkle.root(leaves + [b"\xee" * 32])
        assert not merkle.verify_inclusion(leaves[i], i, n + 1, proof, bigger)       # proof for another tree
        assert not merkle.verify_inclusion(b"\xff" * 32, i, n, proof, r)              # wrong leaf
        if n > 1:
            assert not merkle.verify_inclusion(leaves[i], (i + 1) % n, n, proof, r)   # wrong index
            bad = list(proof)
            bad[0] = bytes(32)
            assert not merkle.verify_inclusion(leaves[i], i, n, bad, r)               # tampered path


def test_out_of_range_index():
    leaves = _leaves(4)
    with pytest.raises(IndexError):
        merkle.inclusion_proof(leaves, 4)
    assert not merkle.verify_inclusion(leaves[0], 4, 4, [], merkle.root(leaves))


def test_order_matters_and_leaf_node_separation():
    a, b = _leaves(2)
    assert merkle.root([a, b]) != merkle.root([b, a])
    # a 2-leaf root must not equal a 1-leaf tree whose leaf is the concatenated children (0x00/0x01 prefixes)
    assert merkle.root([a, b]) != merkle.root([merkle.leaf_hash(a) + merkle.leaf_hash(b)])


def test_root_hex():
    hs = [hashlib.sha256(bytes([i])).hexdigest() for i in range(6)]
    assert merkle.root_hex(hs) == merkle.root([bytes.fromhex(h) for h in hs]).hex()
