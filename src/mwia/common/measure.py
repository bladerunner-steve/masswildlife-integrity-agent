"""Module measurement (agent_id), computed at runtime from the files actually on disk.

code_digest          = SHA-256(JCS(sorted [{path, sha256(file bytes)}])) over a module's own sources plus the
                       manifest's shared sources (paths are repo-relative, POSIX style)
tool_manifest_digest = SHA-256(bytes of config/tool_manifest.yaml)
policy_digest        = SHA-256(bytes of config/policy.yaml)  (the same policy hash PR0 records)
agent_id             = SHA-256("code_digest|tool_manifest_digest|policy_digest|notary_key_id")
Raw bytes are hashed. .gitattributes pins LF line endings so checkouts on different OSes measure the same.
AI-assisted (Claude). Verified by: tests/test_measurement.py (order independence, one-byte change detection,
manifest/policy/key changes, missing files).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .canonical import hash_obj, sha256_hex


def file_sha256(path: Path) -> str:
    return sha256_hex(Path(path).read_bytes())


def code_digest(files: list[Path], root: Path) -> str:
    root = Path(root).resolve()
    entries = []
    for f in files:
        p = (root / f).resolve() if not Path(f).is_absolute() else Path(f).resolve()
        rel = p.relative_to(root).as_posix()  # raises if a source lies outside the repo
        if not p.is_file():
            raise FileNotFoundError(f"measured source missing: {rel}")
        entries.append({"path": rel, "sha256": file_sha256(p)})
    if not entries:
        raise ValueError("a module must have at least one measured source")
    entries.sort(key=lambda e: e["path"])
    if len({e["path"] for e in entries}) != len(entries):
        raise ValueError("duplicate measured source")
    return hash_obj(entries)


def agent_id(code: str, tool_manifest: str, policy: str, notary_key_id: str) -> str:
    return sha256_hex("|".join((code, tool_manifest, policy, notary_key_id)).encode("ascii"))


def load_manifest(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def module_measurements(root: Path, manifest_path: Path, policy_path: Path, notary_key_id: str) -> dict[str, str]:
    """Expected agent_id for each module declared in the tool manifest."""
    manifest = load_manifest(manifest_path)
    shared = list(manifest.get("shared_sources", []))
    tm, pol = file_sha256(manifest_path), file_sha256(policy_path)
    out = {}
    for name, spec in manifest["modules"].items():
        out[name] = agent_id(code_digest(list(spec["sources"]) + shared, root), tm, pol, notary_key_id)
    return out
