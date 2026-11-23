"""Loads policy.yaml (raw bytes + SHA-256 + parsed form), tool_manifest.yaml and settings.yaml.

The policy hash is over the exact file bytes, which is also what PR0 stores as evidence. The verifier
re-evaluates the policy from that signed snapshot, not from this file on disk.
AI-assisted (Claude). Verified by: tests/test_pipeline.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from mwia.common.canonical import sha256_hex

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Config:
    root: Path
    policy_path: Path
    policy_bytes: bytes
    policy: dict
    policy_sha256: str
    manifest_path: Path
    manifest_bytes: bytes
    manifest: dict
    manifest_sha256: str
    settings: dict
    data_root: Path  # vault, anchors, reports and lock file (= root in production, a temp dir in tests)


def load(root: Path = ROOT, policy_path: Path | None = None, data_root: Path | None = None) -> Config:
    root = Path(root)
    pp = Path(policy_path) if policy_path else root / "config" / "policy.yaml"
    mp = root / "config" / "tool_manifest.yaml"
    pb, mb = pp.read_bytes(), mp.read_bytes()
    settings = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8"))
    return Config(root, pp, pb, yaml.safe_load(pb), sha256_hex(pb), mp, mb, yaml.safe_load(mb), sha256_hex(mb),
                  settings, Path(data_root) if data_root else root)
