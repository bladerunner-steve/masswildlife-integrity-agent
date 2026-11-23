"""Module measurement tests for mwia.common.measure. AI-assisted (Claude)."""
import shutil
from pathlib import Path

import pytest
import yaml

from mwia.common.measure import agent_id, code_digest, file_sha256, module_measurements

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_bytes(b"print('a')\n")
    (tmp_path / "src" / "b.py").write_bytes(b"print('b')\n")
    (tmp_path / "src" / "shared.py").write_bytes(b"X = 1\n")
    (tmp_path / "manifest.yaml").write_text(yaml.safe_dump({
        "shared_sources": ["src/shared.py"],
        "modules": {"M1": {"sources": ["src/a.py"]}, "M2": {"sources": ["src/b.py"]}}}), encoding="utf-8")
    (tmp_path / "policy.yaml").write_bytes(b"policy_version: 1\n")
    return tmp_path


def _measure(repo, kid="0123456789abcdef"):
    return module_measurements(repo, repo / "manifest.yaml", repo / "policy.yaml", kid)


def test_order_independent(repo):
    assert code_digest(["src/a.py", "src/shared.py"], repo) == code_digest(["src/shared.py", "src/a.py"], repo)


def test_one_byte_change_changes_only_that_module(repo):
    before = _measure(repo)
    (repo / "src" / "a.py").write_bytes(b"print('A')\n")
    after = _measure(repo)
    assert after["M1"] != before["M1"] and after["M2"] == before["M2"]


def test_line_endings_are_measured(repo):
    before = _measure(repo)["M1"]
    (repo / "src" / "a.py").write_bytes(b"print('a')\r\n")
    assert _measure(repo)["M1"] != before


@pytest.mark.parametrize("target", ["src/shared.py", "manifest.yaml", "policy.yaml"])
def test_shared_inputs_change_every_module(repo, target):
    before = _measure(repo)
    with open(repo / target, "ab") as f:
        f.write(b"# changed\n")
    after = _measure(repo)
    assert all(after[m] != before[m] for m in before)


def test_key_id_changes_measurement(repo):
    assert _measure(repo, "0" * 16) != _measure(repo, "f" * 16)


def test_agent_id_definition(repo):
    import hashlib
    c, t, p, k = "1" * 64, "2" * 64, "3" * 64, "abcdef0123456789"
    assert agent_id(c, t, p, k) == hashlib.sha256(f"{c}|{t}|{p}|{k}".encode()).hexdigest()


def test_missing_or_outside_sources_fail(repo, tmp_path_factory):
    with pytest.raises(FileNotFoundError):
        code_digest(["src/missing.py"], repo)
    outside = tmp_path_factory.mktemp("elsewhere") / "x.py"
    outside.write_text("x")
    with pytest.raises(ValueError):
        code_digest([outside], repo)
    with pytest.raises(ValueError):
        code_digest([], repo)


def test_repo_manifest_lists_existing_shared_sources():
    manifest = yaml.safe_load((REPO / "config" / "tool_manifest.yaml").read_text(encoding="utf-8"))
    for s in manifest["shared_sources"]:
        assert (REPO / s).is_file(), s
    assert set(manifest["modules"]) == {"M0:plan", "M1:request", "M2:response", "M3:filter", "M4:db", "M5:complete"}
    assert len(file_sha256(REPO / "config" / "policy.yaml")) == 64
