"""Tests for scripts/precommit_check.py. All "secrets" here are made up. AI-assisted (Claude)."""
import base64
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import precommit_check as pc  # noqa: E402


def fake_jwt() -> bytes:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=")
    return enc({"alg": "HS512"}) + b"." + enc({"user_id": 1, "exp": 1999999999}) + b".c2lnbmF0dXJlLXNpZw"


@pytest.mark.parametrize("path", [".env", ".env.local", "sub/.env", "keys/private/a.key.pem", "vault/LEDGER.jsonl",
                                  "vault-test/runs/x.json", "anchors/anchors.txt", "data/source/MassWildlife.csv",
                                  "logs/agent-20261123.log", "reports/runs/r/report.json", "notary.pem", "x/y.key"])
def test_blocked_paths(path):
    assert pc.check([(path, b"harmless")], []) != []


@pytest.mark.parametrize("path", [".env.example", "keys/public/a62a04bf20ca2931.pub.pem", "keys/public/keyring.json",
                                  "src/mwia/verify/engine.py", "eval/results/summary.md", "examples/green/badge.svg"])
def test_allowed_paths(path):
    assert pc.check([(path, b"harmless")], []) == []


PK = b"PRIVATE " + b"KEY-----"  # assembled at runtime so this file itself passes the scanner


def test_content_checks():
    assert pc.check([("notes.md", b"token: " + fake_jwt())], []) == [("notes.md", "looks like a JSON Web Token (JWT)")]
    assert pc.check([("a.txt", b"-----BEGIN ENCRYPTED " + PK + b"\nMIIB")], [])[0][1] == "contains a PEM private key"
    assert pc.check([("a.txt", b"-----BEGIN OPENSSH " + PK)], []) != []
    assert pc.check([("a.txt", b"-----BEGIN PUBLIC KEY-----")], []) == []
    assert pc.check([("cfg.py", b"pw = 'S3cret-Value!'")], [b"S3cret-Value!"]) == [("cfg.py", "contains a secret value from .env")]


def test_local_secrets_ignore_placeholders_and_short_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MYSQL_PASSWORD=change_me\nNOTARY_KEY_PASSPHRASE=a-long-enough-passphrase\nINAT_API_TOKEN=\n"
                   "MYSQL_USER=claude\n")
    assert pc.local_secrets(env) == [b"a-long-enough-passphrase"]


def test_repository_as_it_would_be_committed_is_clean():
    """Everything `git add -A` would add today passes the check (with the real .env values compared in memory)."""
    problems = pc.check(pc.would_add_files(), pc.local_secrets(REPO / ".env"))
    assert problems == [], problems
