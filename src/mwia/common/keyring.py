"""Public-key side of the notary keyring: key ids and loading trusted Ed25519 public keys.

notary_key_id = first 16 hex chars of SHA-256(raw 32-byte Ed25519 public key).
Layout: <keys>/public/<key_id>.pub.pem and <keys>/public/keyring.json (active key, created/retired times).
This module never touches private keys; the verifier uses it with a directory of trusted public keys.
AI-assisted (Claude). Verified by: tests/test_notary_keys.py (key id derivation, rotation keeps old keys,
mislabeled key file rejected).
"""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .canonical import sha256_hex

PUB_SUFFIX = ".pub.pem"
KEYRING_FILE = "keyring.json"


def key_id_for(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return sha256_hex(raw)[:16]


def load_public_key_pem(data: bytes) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("public key is not Ed25519")
    return key


def load_trusted_keys(public_dir: Path) -> dict[str, Ed25519PublicKey]:
    """All public keys in public_dir, keyed by derived key id. A file whose name disagrees with its key is
    an error, not something to skip silently."""
    keys: dict[str, Ed25519PublicKey] = {}
    for p in sorted(Path(public_dir).glob(f"*{PUB_SUFFIX}")):
        key = load_public_key_pem(p.read_bytes())
        kid = key_id_for(key)
        if p.name != f"{kid}{PUB_SUFFIX}":
            raise ValueError(f"public key file {p.name} does not match its key id {kid}")
        keys[kid] = key
    return keys


def read_keyring(public_dir: Path) -> dict:
    return json.loads((Path(public_dir) / KEYRING_FILE).read_text(encoding="utf-8"))
