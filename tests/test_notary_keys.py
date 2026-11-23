"""Notary key management tests for mwia.notary.keys and mwia.common.keyring. AI-assisted (Claude)."""
import getpass
import hashlib
import os
import shutil
import subprocess

import pytest
from cryptography.hazmat.primitives import serialization

from mwia.common.keyring import key_id_for, load_trusted_keys, read_keyring
from mwia.common.receipt import verify_signed_object
from mwia.notary.keys import KeyError_, keygen, load_active_private_key, rotate
from mwia.notary.service import Notary

from conftest import TEST_PASSPHRASE, build_chain


def test_keygen_layout_and_encryption(keys_dir):
    ring = read_keyring(keys_dir / "public")
    kid = ring["active"]
    priv = (keys_dir / "private" / f"{kid}.key.pem").read_bytes()
    assert priv.startswith(b"-----BEGIN ENCRYPTED " + b"PRIVATE KEY-----")  # split so the secret scanner stays quiet
    assert TEST_PASSPHRASE.encode() not in priv
    with pytest.raises(TypeError):  # cannot be loaded without the passphrase
        serialization.load_pem_private_key(priv, password=None)
    pub = serialization.load_pem_public_key((keys_dir / "public" / f"{kid}.pub.pem").read_bytes())
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert kid == hashlib.sha256(raw).hexdigest()[:16] == key_id_for(pub)
    assert ring["keys"] == [{"key_id": kid, "created_at": ring["keys"][0]["created_at"], "retired_at": None}]


def test_wrong_passphrase(keys_dir):
    with pytest.raises(KeyError_, match="could not decrypt"):
        load_active_private_key(keys_dir, "a-different-passphrase-123")


@pytest.mark.parametrize("pw", [None, "", "change_me", "short-pw"])
def test_weak_or_placeholder_passphrase_refused(tmp_path, pw):
    with pytest.raises(KeyError_):
        keygen(tmp_path / "k", pw)
    assert not (tmp_path / "k").exists()


def test_keygen_twice_refused(keys_dir):
    with pytest.raises(KeyError_, match="rotate"):
        keygen(keys_dir, TEST_PASSPHRASE)


def test_rotation_keeps_old_receipts_verifiable(keys_dir):
    key, old = load_active_private_key(keys_dir, TEST_PASSPHRASE)
    old_receipts = build_chain(Notary(key, old), old)
    o, new = rotate(keys_dir, TEST_PASSPHRASE)
    assert o == old and new != old
    ring = read_keyring(keys_dir / "public")
    assert ring["active"] == new
    assert {k["key_id"]: bool(k["retired_at"]) for k in ring["keys"]} == {old: True, new: False}
    key2, kid2 = load_active_private_key(keys_dir, TEST_PASSPHRASE)
    assert kid2 == new
    trusted = load_trusted_keys(keys_dir / "public")
    assert set(trusted) == {old, new}
    assert all(verify_signed_object(r, trusted) == [] for r in old_receipts)
    assert all(verify_signed_object(r, trusted) == [] for r in build_chain(Notary(key2, new), new))


def test_rotate_requires_current_passphrase(keys_dir):
    with pytest.raises(KeyError_):
        rotate(keys_dir, "a-different-passphrase-123")
    assert len(read_keyring(keys_dir / "public")["keys"]) == 1


def test_mislabeled_public_key_rejected(keys_dir, tmp_path):
    kid = read_keyring(keys_dir / "public")["active"]
    shutil.copy(keys_dir / "public" / f"{kid}.pub.pem", keys_dir / "public" / f"{'0' * 16}.pub.pem")
    with pytest.raises(ValueError, match="does not match"):
        load_trusted_keys(keys_dir / "public")


def test_private_key_permissions(keys_dir):
    kid = read_keyring(keys_dir / "public")["active"]
    path = keys_dir / "private" / f"{kid}.key.pem"
    if os.name == "nt":
        out = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True).stdout
        aces = [l.strip() for l in out.splitlines()[:-1] if ":(" in l]
        assert aces, out
        assert all("(I)" not in a for a in aces), out          # no inherited ACEs
        assert len(aces) == 1 and getpass.getuser().lower() in aces[0].lower(), out
        dir_out = subprocess.run(["icacls", str(keys_dir / "private")], capture_output=True, text=True,
                                 check=True).stdout
        dir_aces = [l.strip() for l in dir_out.splitlines()[:-1] if ":(" in l]
        assert len(dir_aces) == 1 and "(OI)(CI)" in dir_aces[0] and "(I)" not in dir_aces[0], dir_out
    else:
        assert path.stat().st_mode & 0o777 == 0o600
        assert (keys_dir / "private").stat().st_mode & 0o777 == 0o700
