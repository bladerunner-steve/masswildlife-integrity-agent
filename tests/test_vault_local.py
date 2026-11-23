"""LocalWormVault tests: write-once semantics, OS-level hardening, retention, ledger and object tampering.
AI-assisted (Claude)."""
import os
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from mwia.common.canonical import hash_obj, jcs, sha256_hex
from mwia.common.fsperm import IS_WINDOWS
from mwia.common.timeutil import parse_utc
from mwia.vault import ObjectExists, RetentionError, VaultError, open_vault
from mwia.vault.base import IntegrityError, VaultBackend, blob_path
from mwia.vault.local import LocalWormVault

from conftest import force_writable, ledger_entries, rewrite_ledger

K = "runs/2026-11-23/11111111-2222-3333-4444-555555555555/0-plan.json"


def _fill(vault, n=4):
    keys = [f"runs/2026-11-23/r/{i}-x.json" for i in range(n)]
    for i, k in enumerate(keys):
        vault.put_json(k, {"i": i})
    return keys


def codes(problems):
    return sorted({p.code for p in problems})


# ---------------- basic semantics ----------------

def test_put_get_head_and_blob(vault, vault_root):
    info = vault.put_json(K, {"b": 1, "a": 2})
    data = vault.get(K)
    assert data == jcs({"a": 2, "b": 1}) == b'{"a":2,"b":1}'
    assert info.sha256 == sha256_hex(data) == hash_obj({"a": 2, "b": 1})
    assert info.mode == "COMPLIANCE"
    days = (parse_utc(info.retain_until) - datetime.now(timezone.utc)).days
    assert 364 <= days <= 365
    assert (vault_root / blob_path(info.sha256)).read_bytes() == data
    assert vault.head(K) == info and vault.exists(K) and vault.list_keys("runs/") == [K]
    assert vault.verify() == []


def test_identical_content_shares_one_blob(vault, vault_root):
    a = vault.put(f"{K}.a", b"same")
    b = vault.put(f"{K}.b", b"same")
    assert a.sha256 == b.sha256
    assert vault.verify() == []


def test_overwrite_refused(vault):
    vault.put(K, b"original")
    with pytest.raises(ObjectExists):
        vault.put(K, b"replacement")
    assert vault.get(K) == b"original"
    assert vault.ledger_head()[0] == 0  # only the first put was ledgered


def test_overwrite_refused_after_reopen(vault, vault_root):
    vault.put(K, b"original")
    again = LocalWormVault(vault_root)
    with pytest.raises(ObjectExists):
        again.put(K, b"replacement")


def test_no_delete_or_overwrite_api():
    for name in ("delete", "remove", "overwrite", "delete_object", "unlink", "set_retention", "shorten_retention"):
        assert not hasattr(VaultBackend, name) and not hasattr(LocalWormVault, name), name


@pytest.mark.parametrize("key", ["../x", "/abs", "objects/sha256/x", "ledger/1", "LEDGER.jsonl", "vault.json", "a//b",
                                 "a/./b", "a/../b", "", "x" * 300, "runs/a b", "runs\\x", ".hidden/x"])
def test_invalid_keys(vault, key):
    with pytest.raises(VaultError):
        vault.put(key, b"x")


# ---------------- OS-level hardening ----------------

def test_os_delete_and_write_refused(vault, vault_root):
    vault.put(K, b"protected")
    f = vault_root / K
    with pytest.raises(PermissionError):
        os.remove(f)
    with pytest.raises(PermissionError):
        open(f, "wb")
    assert f.read_bytes() == b"protected"
    if IS_WINDOWS:
        with pytest.raises(OSError):
            shutil.rmtree(vault_root / "runs")
        assert f.read_bytes() == b"protected"
        with pytest.raises(PermissionError):  # deny WA: the read-only flag can't simply be cleared
            os.chmod(f, 0o666)
        with pytest.raises(PermissionError):
            os.remove(vault_root / "LEDGER.jsonl")
    else:
        assert f.stat().st_mode & 0o777 == 0o444


# ---------------- retention ----------------

def test_retention_extend_only(vault):
    info = vault.put(K, b"x")
    later = parse_utc(info.retain_until) + timedelta(days=30)
    ext = vault.extend_retention(K, later)
    assert parse_utc(ext.retain_until) == later and vault.head(K).retain_until == ext.retain_until
    with pytest.raises(RetentionError):
        vault.extend_retention(K, later - timedelta(days=1))          # shorten
    with pytest.raises(RetentionError):
        vault.extend_retention(K, later)                               # equal is not an extension
    with pytest.raises(VaultError):
        vault.extend_retention("runs/missing.json", later)
    assert [e["event"] for e in ledger_entries(vault.root)] == ["put", "extend_retention"]
    assert vault.verify() == []


def test_vault_default_retention_cannot_be_lowered(vault_root):
    LocalWormVault(vault_root, retention_days=365)
    with pytest.raises(RetentionError):
        LocalWormVault(vault_root, retention_days=30)
    LocalWormVault(vault_root, retention_days=400)  # raising is allowed
    with pytest.raises(RetentionError):
        LocalWormVault(vault_root.parent / "other", retention_days=0)


def test_forged_retention_shortening_in_ledger_detected(vault, vault_root):
    info = vault.put(K, b"x")
    entries = ledger_entries(vault_root)
    shorter = dict(entries[0], event="extend_retention", retain_until="2027-01-01T00:00:00.000000Z")
    force_writable(vault_root / "LEDGER.jsonl")
    rewrite_ledger(vault_root, entries + [shorter])
    assert "retention_shortened" in codes(LocalWormVault(vault_root).verify())


# ---------------- ledger tampering ----------------

def test_clean_vault_verifies(vault):
    _fill(vault)
    assert vault.verify() == []


def _lines(root):
    return (root / "LEDGER.jsonl").read_bytes().splitlines()


def _write_lines(root, lines):
    (root / "LEDGER.jsonl").write_bytes(b"".join(l + b"\n" for l in lines))


def test_modified_ledger_line_detected(vault, vault_root):
    _fill(vault)
    lines = _lines(vault_root)
    import json
    e = json.loads(lines[1])
    e["sha256"] = "0" * 64
    lines[1] = jcs(e)
    _write_lines(vault_root, lines)
    probs = LocalWormVault(vault_root).verify()
    assert "ledger_chain_break" in codes(probs)
    assert any(p.code == "ledger_chain_break" and p.seq == 2 for p in probs)


def test_removed_ledger_line_detected(vault, vault_root):
    _fill(vault)
    lines = _lines(vault_root)
    _write_lines(vault_root, lines[:1] + lines[2:])
    assert {"ledger_seq_gap", "ledger_chain_break", "unledgered_object"} <= set(codes(LocalWormVault(vault_root).verify()))


def test_appended_forged_line_detected(vault, vault_root):
    _fill(vault)
    import json
    e = dict(json.loads(_lines(vault_root)[-1]), seq=4, key="runs/forged.json", prev="f" * 64)
    with open(vault_root / "LEDGER.jsonl", "ab") as f:
        f.write(jcs(e) + b"\n")
    assert "ledger_chain_break" in codes(LocalWormVault(vault_root).verify())


@pytest.mark.parametrize("bad,code", [(b"not json", "ledger_malformed"), (None, "ledger_noncanonical")])
def test_malformed_and_noncanonical_lines(vault, vault_root, bad, code):
    import json
    _fill(vault, 2)
    lines = _lines(vault_root)
    lines[1] = bad if bad is not None else json.dumps(json.loads(lines[1]), indent=1).encode().replace(b"\n", b" ")
    _write_lines(vault_root, lines)
    assert code in codes(LocalWormVault(vault_root).verify())


def test_consistent_ledger_rewrite_still_leaves_evidence(vault, vault_root):
    """An attacker who drops an entry and recomputes the whole chain passes the chain check, but the object
    file is still on disk (unledgered). Deleting it too is caught only by anchors (see test_anchor.py)."""
    keys = _fill(vault)
    entries = [e for e in ledger_entries(vault_root) if e["key"] != keys[2]]
    rewrite_ledger(vault_root, entries)
    assert codes(LocalWormVault(vault_root).verify()) == ["unledgered_object"]


def test_writer_refuses_to_append_to_tampered_ledger(vault, vault_root):
    _fill(vault)
    lines = _lines(vault_root)
    _write_lines(vault_root, lines[:1] + lines[2:])
    with pytest.raises(IntegrityError):
        LocalWormVault(vault_root).put("runs/new.json", b"x")


# ---------------- object tampering ----------------

def test_object_content_tampering_detected(vault, vault_root):
    keys = _fill(vault)
    f = vault_root / keys[1]
    force_writable(f)
    f.write_bytes(b'{"i":999}')
    probs = vault.verify()
    assert [(p.code, p.key) for p in probs] == [("object_hash_mismatch", keys[1])]


def test_missing_blob_and_stray_file_detected(vault, vault_root):
    keys = _fill(vault)
    blob = vault_root / blob_path(vault.head(keys[0]).sha256)
    force_writable(blob)
    blob.unlink()
    stray = vault_root / "runs" / "2026-11-23" / "r" / "stray.json"  # adding files is not denied, only removal
    stray.write_bytes(b"{}")
    assert codes(vault.verify()) == ["blob_missing", "unledgered_object"]


# ---------------- multiple writers / config ----------------

def test_two_instances_share_one_consistent_ledger(vault_root):
    a, b = LocalWormVault(vault_root), LocalWormVault(vault_root)
    a.put("runs/a.json", b"a")
    b.put("runs/b.json", b"b")
    a.put("runs/c.json", b"c")
    with pytest.raises(ObjectExists):
        b.put("runs/a.json", b"a2")
    assert [e["seq"] for e in ledger_entries(vault_root)] == [0, 1, 2]
    assert a.verify() == []


def test_open_vault_from_settings(tmp_path):
    from conftest import unharden_tree
    settings = {"vault": {"backend": "local", "roots": {"prod": "v", "test": "vt"}, "retention_days": 365}}
    try:
        v = open_vault(settings, "test", tmp_path)
        assert isinstance(v, LocalWormVault) and v.root == tmp_path / "vt"
        with pytest.raises(VaultError):
            open_vault(settings, "staging", tmp_path)
    finally:
        unharden_tree(tmp_path / "vt")
