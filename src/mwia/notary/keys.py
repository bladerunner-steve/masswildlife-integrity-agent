"""Notary key management (private side): keygen, rotate, and loading the active signing key.

Private keys: <keys>/private/<key_id>.key.pem, PKCS#8 PEM encrypted with NOTARY_KEY_PASSPHRASE
(cryptography BestAvailableEncryption). Permissions: chmod 600 on POSIX; on Windows, icacls removes inherited
ACEs and grants only the current user. Public keys: <keys>/public/<key_id>.pub.pem plus keyring.json. Rotation
marks the old key retired and keeps its public key, so old receipts stay verifiable. Retired private keys are
kept encrypted but are never used to sign again.
AI-assisted (Claude). Verified by: tests/test_notary_keys.py (encryption, wrong passphrase, permissions,
rotation, key id/file consistency).
"""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mwia.common.fsperm import owner_only
from mwia.common.keyring import KEYRING_FILE, PUB_SUFFIX, key_id_for, load_public_key_pem, read_keyring
from mwia.common.timeutil import utc_now

PASSPHRASE_ENV = "NOTARY_KEY_PASSPHRASE"
MIN_PASSPHRASE_LEN = 12
PLACEHOLDERS = {"change_me", "changeme", "placeholder", "passphrase"}
PRIV_SUFFIX = ".key.pem"


class KeyError_(Exception):
    """Key management refused or failed (message never contains the passphrase)."""


def check_passphrase(passphrase: str | None) -> bytes:
    if not passphrase or passphrase.strip().lower() in PLACEHOLDERS:
        raise KeyError_(f"{PASSPHRASE_ENV} is missing or still a placeholder; set it in .env")
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        raise KeyError_(f"{PASSPHRASE_ENV} must be at least {MIN_PASSPHRASE_LEN} characters")
    return passphrase.encode("utf-8")


def restrict_permissions(path: Path) -> None:
    """Owner-only access: chmod 600/700 (POSIX) or an icacls ACL for the current user only (Windows).
    On a directory the Windows grant is inheritable, (OI)(CI). Otherwise files created inside would get the
    process's default DACL (which also grants SYSTEM and the logon session)."""
    owner_only(path)


def _dirs(keys_dir: Path) -> tuple[Path, Path]:
    return Path(keys_dir) / "private", Path(keys_dir) / "public"


def _write_keyring(public_dir: Path, ring: dict) -> None:
    (public_dir / KEYRING_FILE).write_text(json.dumps(ring, indent=2) + "\n", encoding="utf-8")


def _create_key(keys_dir: Path, passphrase: bytes) -> str:
    priv_dir, pub_dir = _dirs(keys_dir)
    priv_dir.mkdir(parents=True, exist_ok=True)
    pub_dir.mkdir(parents=True, exist_ok=True)
    restrict_permissions(priv_dir)
    key = Ed25519PrivateKey.generate()
    kid = key_id_for(key.public_key())
    priv_path = priv_dir / f"{kid}{PRIV_SUFFIX}"
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.BestAvailableEncryption(passphrase))
    with open(priv_path, "xb") as f:  # "x": never overwrite an existing key
        f.write(pem)
    restrict_permissions(priv_path)
    pub_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo)
    with open(pub_dir / f"{kid}{PUB_SUFFIX}", "xb") as f:
        f.write(pub_pem)
    return kid


def keygen(keys_dir: Path, passphrase: str | None) -> str:
    """Create the first notary key. Refuses if a keyring already exists (use rotate)."""
    pw = check_passphrase(passphrase)
    _, pub_dir = _dirs(keys_dir)
    if (pub_dir / KEYRING_FILE).exists():
        raise KeyError_("a keyring already exists; use `notary rotate` to replace the active key")
    kid = _create_key(keys_dir, pw)
    _write_keyring(pub_dir, {"active": kid, "keys": [{"key_id": kid, "created_at": utc_now(), "retired_at": None}]})
    return kid


def rotate(keys_dir: Path, passphrase: str | None) -> tuple[str, str]:
    """Create a new active key and retire the old one (its public key is kept). Returns (old, new)."""
    pw = check_passphrase(passphrase)
    _, pub_dir = _dirs(keys_dir)
    ring = read_keyring(pub_dir)
    old = ring["active"]
    load_active_private_key(keys_dir, passphrase)  # must know the current passphrase to rotate
    new = _create_key(keys_dir, pw)
    now = utc_now()
    for k in ring["keys"]:
        if k["key_id"] == old:
            k["retired_at"] = now
    ring["keys"].append({"key_id": new, "created_at": now, "retired_at": None})
    ring["active"] = new
    _write_keyring(pub_dir, ring)
    return old, new


def load_active_private_key(keys_dir: Path, passphrase: str | None) -> tuple[Ed25519PrivateKey, str]:
    """Decrypt the active key and check it against its id and its published public key."""
    pw = check_passphrase(passphrase)
    priv_dir, pub_dir = _dirs(keys_dir)
    kid = read_keyring(pub_dir)["active"]
    try:
        key = serialization.load_pem_private_key((priv_dir / f"{kid}{PRIV_SUFFIX}").read_bytes(), password=pw)
    except (ValueError, TypeError):
        raise KeyError_("could not decrypt the notary key (wrong passphrase or corrupt key file)") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise KeyError_("notary key is not Ed25519")
    if key_id_for(key.public_key()) != kid:
        raise KeyError_("active private key does not match its key id")
    published = load_public_key_pem((pub_dir / f"{kid}{PUB_SUFFIX}").read_bytes())
    if key_id_for(published) != kid:
        raise KeyError_("published public key does not match the active key")
    return key, kid
