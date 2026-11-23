"""Shared pytest fixtures: a throwaway notary key in tmp_path, an in-process notary and a chain builder.

Test-only passphrase; it protects nothing real. AI-assisted (Claude).
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import uuid
from pathlib import Path

import pytest

from mwia.common.canonical import ZERO_HASH, hash_obj
from mwia.common.keyring import load_trusted_keys
from mwia.common.receipt import new_receipt_body
from mwia.notary.keys import keygen, load_active_private_key
from mwia.notary.service import Notary

TEST_PASSPHRASE = "test-passphrase-not-a-secret-42"
MODULES = ["M0:plan", "M1:request", "M2:response", "M3:filter", "M4:db", "M5:complete"]


@pytest.fixture
def keys_dir(tmp_path):
    d = tmp_path / "keys"
    keygen(d, TEST_PASSPHRASE)
    return d


@pytest.fixture
def notary(keys_dir):
    key, kid = load_active_private_key(keys_dir, TEST_PASSPHRASE)
    return Notary(key, kid)


@pytest.fixture
def trusted(keys_dir):
    return load_trusted_keys(keys_dir / "public")


# ---------------- vault helpers ----------------
# Hardened test vaults can't be removed by pytest's tmp cleanup, so each fixture lifts the deny ACEs and
# read-only flags afterwards. That is the step an attacker with the owner's rights would also have to take.

def force_writable(path: Path) -> None:
    """Simulate an owner/admin lifting the protection on one file (and its directory) to tamper with it."""
    from mwia.common.fsperm import IS_WINDOWS, current_principal
    for p in (path, path.parent):
        if IS_WINDOWS:
            subprocess.run(["icacls", str(p), "/remove:d", current_principal()], capture_output=True, check=True)
        os.chmod(p, stat.S_IREAD | stat.S_IWRITE | (stat.S_IEXEC if p.is_dir() else 0))


def unharden_tree(root: Path) -> None:
    from mwia.common.fsperm import IS_WINDOWS, current_principal
    if not root.exists():
        return
    if IS_WINDOWS:
        subprocess.run(["icacls", str(root), "/remove:d", current_principal(), "/T", "/C", "/Q"], capture_output=True)
    for p in [root, *root.rglob("*")]:
        try:
            os.chmod(p, stat.S_IREAD | stat.S_IWRITE | (stat.S_IEXEC if p.is_dir() else 0))
        except OSError:
            pass


@pytest.fixture
def vault_root(tmp_path):
    root = tmp_path / "vault"
    yield root
    unharden_tree(root)


@pytest.fixture
def vault(vault_root):
    from mwia.vault.local import LocalWormVault
    return LocalWormVault(vault_root)


def rewrite_ledger(vault_root: Path, entries: list[dict]) -> None:
    """Attacker with write access rewrites LEDGER.jsonl consistently (recomputing seq and prev)."""
    from mwia.common.canonical import ZERO_HASH, sha256_hex
    from mwia.vault.ledger import encode
    prev, out = ZERO_HASH, []
    for i, e in enumerate(entries):
        line = encode(dict(e, seq=i, prev=prev))
        out.append(line)
        prev = sha256_hex(line)
    (vault_root / "LEDGER.jsonl").write_bytes(b"".join(l + b"\n" for l in out))


def ledger_entries(vault_root: Path) -> list[dict]:
    return [json.loads(l) for l in (vault_root / "LEDGER.jsonl").read_bytes().splitlines() if l]


def make_body(key_id: str, run_id: str, step: int, prev_hash: str, spec_hash: str | None, **over) -> dict:
    body = new_receipt_body(
        run_id=run_id, step=step, module=MODULES[step], model_id=f"deterministic-test-v1",
        agent_id=hash_obj({"agent": MODULES[step]}), in_hash=hash_obj({"in": step}), out_hash=hash_obj({"out": step}),
        evidence=[{"key": f"runs/x/{run_id}/{step}.json", "sha256": hash_obj({"ev": step}), "role": "output"}],
        spec_hash=spec_hash, prev_hash=prev_hash, policy_decision="n/a", policy_rules_evaluated=[],
        notary_key_id=key_id, payload={"step": step},
    )
    body.update(over)
    return body


def build_chain(signer, key_id: str, steps=range(6), run_id: str | None = None, prev_seal: str = ZERO_HASH) -> list[dict]:
    """Sign a chain of receipts for the given steps through `signer` (Notary or NotaryClient)."""
    run_id = run_id or str(uuid.uuid4())
    receipts: list[dict] = []
    prev, spec = prev_seal, None
    for s in steps:
        r = signer.sign_receipt(make_body(key_id, run_id, s, prev, spec))
        receipts.append(r)
        prev = r["receipt_hash"]
        if s == 0:
            spec = r["receipt_hash"]
    return receipts
