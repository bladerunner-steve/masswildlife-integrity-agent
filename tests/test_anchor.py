"""External anchor tests (mwia.vault.anchor): rollback, deletion and ledger rewrites that the vault alone
cannot see. AI-assisted (Claude)."""
import json
import shutil
import subprocess

import pytest

from mwia.common.canonical import hash_obj
from mwia.vault import seal_key
from mwia.vault.anchor import AnchorLog, check_anchors, find_git
from mwia.vault.local import LocalWormVault

from conftest import force_writable, ledger_entries, rewrite_ledger, unharden_tree


def _run(vault, n):
    rid = f"00000000-0000-0000-0000-{n:012d}"
    for s in range(3):
        vault.put_json(f"runs/2026-11-23/{rid}/{s}-x.json", {"run": n, "step": s})
    body = {"run_id": rid, "n": n}
    seal = {"body": body, "seal_hash": hash_obj(body), "signature": "00"}
    vault.put_json(seal_key("2026-11-23", rid), seal)
    return rid, seal["seal_hash"]


def _anchored_runs(vault, log, k=2):
    out = []
    for n in range(k):
        rid, h = _run(vault, n)
        log.append(rid, h, *vault.ledger_head())
        out.append((rid, h))
    return out


def codes(problems):
    return sorted({p.code for p in problems})


@pytest.fixture
def log(tmp_path):
    return AnchorLog(tmp_path / "anchors" / "anchors.txt", git=False)


def test_clean_anchors(vault, log):
    _anchored_runs(vault, log)
    assert check_anchors(vault, log.path) == []
    assert vault.verify() == []


def test_missing_anchor(vault, log):
    _run(vault, 0)
    assert codes(check_anchors(vault, log.path)) == ["anchor_missing"]


def test_rollback_of_latest_run_detected(vault, vault_root, log):
    """Attacker deletes the newest run's objects and rewrites the ledger consistently: the vault looks clean
    on its own, and only the external anchor reveals the rollback."""
    (rid0, _), (rid1, _) = _anchored_runs(vault, log)
    gone = [e for e in ledger_entries(vault_root) if rid1 in e["key"]]
    for e in gone:
        f = vault_root / e["key"]
        force_writable(f)
        f.unlink()
        blob = vault_root / "objects" / "sha256" / e["sha256"][:2] / e["sha256"]
        if blob.exists():
            force_writable(blob)
            blob.unlink()
    force_writable(vault_root / "LEDGER.jsonl")
    rewrite_ledger(vault_root, [e for e in ledger_entries(vault_root) if rid1 not in e["key"]])
    reopened = LocalWormVault(vault_root)
    assert reopened.verify() == []                                    # internally consistent
    assert codes(check_anchors(reopened, log.path)) == ["anchor_mismatch", "anchored_seal_missing", "ledger_truncated"]


def test_same_length_ledger_rewrite_detected(vault, vault_root, log):
    _anchored_runs(vault, log)
    entries = ledger_entries(vault_root)
    entries[1]["time"] = "2020-01-01T00:00:00.000000Z"            # backdate one event, recompute the chain
    force_writable(vault_root / "LEDGER.jsonl")
    rewrite_ledger(vault_root, entries)
    assert LocalWormVault(vault_root).verify() == []
    assert codes(check_anchors(LocalWormVault(vault_root), log.path)) == ["ledger_rewritten"]


def test_unanchored_seal_detected(vault, log):
    _anchored_runs(vault, log)
    _run(vault, 7)  # a run whose anchoring never happened
    assert codes(check_anchors(vault, log.path)) == ["unanchored_seal"]


def test_malformed_anchor_line(vault, log):
    _anchored_runs(vault, log)
    with open(log.path, "ab") as f:
        f.write(b"garbage\n")
    assert codes(check_anchors(vault, log.path)) == ["anchors_malformed"]


@pytest.mark.skipif(find_git() is None, reason="git not installed")
def test_anchor_commits_to_separate_git_repo(vault, tmp_path):
    log = AnchorLog(tmp_path / "anchor-repo" / "anchors.txt", git=True)
    _anchored_runs(vault, log)
    out = subprocess.run([find_git(), "-C", str(log.path.parent), "log", "--format=%an <%ae>|%s"],
                         capture_output=True, text=True, check=True).stdout.strip().splitlines()
    assert len(out) == 2 and all(l.startswith("mwia-anchor <anchor@localhost>|anchor run ") for l in out)
    assert check_anchors(vault, log.path) == []
