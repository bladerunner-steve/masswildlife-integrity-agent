"""End-to-end tests of the notary as a separate process (mwia.notary.client + `python -m mwia.notary`).
AI-assisted (Claude)."""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from mwia.common.canonical import ZERO_HASH
from mwia.common.keyring import load_trusted_keys
from mwia.common.receipt import verify_signed_object
from mwia.notary.client import SRC_DIR, NotaryClient, NotaryError

from conftest import TEST_PASSPHRASE, build_chain, make_body


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if k != "NOTARY_KEY_PASSPHRASE"}
    env["PYTHONPATH"] = str(SRC_DIR)
    env.update(extra)
    return env


def test_sign_and_seal_over_subprocess(keys_dir, tmp_path):
    with NotaryClient(keys_dir, env_file=tmp_path / "none.env",
                      extra_env={"NOTARY_KEY_PASSPHRASE": TEST_PASSPHRASE}) as n:
        rs = build_chain(n, n.key_id)
        seal = n.seal_run(rs[0]["body"]["run_id"])
    trusted = load_trusted_keys(keys_dir / "public")
    assert all(verify_signed_object(o, trusted) == [] for o in rs + [seal])
    assert seal["body"]["receipt_count"] == 6


def test_refusal_is_reported_and_process_keeps_serving(keys_dir, tmp_path):
    with NotaryClient(keys_dir, env_file=tmp_path / "none.env",
                      extra_env={"NOTARY_KEY_PASSPHRASE": TEST_PASSPHRASE}) as n:
        with pytest.raises(NotaryError, match="must be PR0"):
            n.sign_receipt(make_body(n.key_id, str(uuid.uuid4()), 1, ZERO_HASH, ZERO_HASH))
        assert len(build_chain(n, n.key_id)) == 6


def test_passphrase_read_from_env_file(keys_dir, tmp_path, monkeypatch):
    monkeypatch.delenv("NOTARY_KEY_PASSPHRASE", raising=False)
    env_file = tmp_path / "test.env"
    env_file.write_text(f"NOTARY_KEY_PASSPHRASE={TEST_PASSPHRASE}\n", encoding="utf-8")
    with NotaryClient(keys_dir, env_file=env_file) as n:
        assert len(n.key_id) == 16


def test_wrong_passphrase_fails_without_leaking_it(keys_dir, tmp_path):
    wrong = "wrong-passphrase-0000"
    n = NotaryClient(keys_dir, env_file=tmp_path / "none.env", extra_env={"NOTARY_KEY_PASSPHRASE": wrong})
    with pytest.raises(NotaryError) as e:
        n.start()
    n.close()
    assert "could not decrypt" in str(e.value) and wrong not in str(e.value)


def test_client_import_pulls_in_no_key_code():
    code = ("import sys, mwia.notary.client; "
            "print(sorted(m for m in sys.modules if m.startswith(('mwia', 'cryptography', 'dotenv'))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=_env(), check=True).stdout
    assert out.strip() == "['mwia', 'mwia.notary', 'mwia.notary.client']"


def test_cli_keygen_rotate_pubkey(tmp_path):
    kd = tmp_path / "keys"
    run = lambda *a: subprocess.run([sys.executable, "-m", "mwia.notary", *a, "--keys-dir", str(kd),
                                     "--env-file", str(tmp_path / "none.env")], capture_output=True, text=True,
                                    env=_env(NOTARY_KEY_PASSPHRASE=TEST_PASSPHRASE))
    r1 = run("keygen")
    assert r1.returncode == 0 and "created notary key" in r1.stdout
    assert run("keygen").returncode == 2            # second keygen refused
    r3 = run("rotate")
    assert r3.returncode == 0 and "retired" in r3.stdout
    r4 = run("pubkey")
    assert r4.returncode == 0 and r3.stdout.split()[-2] in r4.stdout
    for r in (r1, r3, r4):
        assert TEST_PASSPHRASE not in r.stdout + r.stderr
