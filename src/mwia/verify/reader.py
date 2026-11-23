"""Read-only access to a vault and grouping of its objects into runs.

ReadOnlyLocalVault implements the VaultBackend read primitives over a vault directory and refuses every
write. It takes no lock and creates no files. Its ledger/object check (verify) and the anchor check reuse
the vault-format code (mwia.vault.base / ledger / anchor), which is pure, format-level logic, not agent code.
A run is everything under runs/<date>/<run_id>/: receipts `<step>-<step_type>.json`, `seal.json`, and
evidence under `evidence/`. Runs are ordered by ledger position.
AI-assisted (Claude). Verified by: tests/test_verify.py.
"""
from __future__ import annotations

import json
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from mwia.vault.base import VaultBackend, VaultError
from mwia.vault.ledger import replay

RECEIPT_RE = re.compile(r"^runs/(?P<date>[^/]+)/(?P<run>[^/]+)/(?P<step>\d+)-(?P<type>[a-z_]+)\.json$")
SEAL_RE = re.compile(r"^runs/(?P<date>[^/]+)/(?P<run>[^/]+)/seal\.json$")


class ReadOnlyLocalVault(VaultBackend):
    def __init__(self, root: Path):
        super().__init__(retention_days=1)
        self.root = Path(root)
        if not (self.root / "LEDGER.jsonl").is_file():
            raise VaultError(f"{self.root} is not a vault (no LEDGER.jsonl)")

    def _full(self, path: str) -> Path:
        return self.root.joinpath(*path.split("/"))

    def _read(self, path: str) -> bytes | None:
        p = self._full(path)
        return p.read_bytes() if p.is_file() else None

    def _list_paths(self) -> list[str]:
        skip = {"LEDGER.jsonl", "vault.json", ".lock"}
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
                      if p.is_file() and p.relative_to(self.root).as_posix() not in skip)

    def _ledger_read(self, cursor):
        data = (self.root / "LEDGER.jsonl").read_bytes()
        parts = data.split(b"\n")
        tail = parts.pop()
        return parts + ([tail] if tail else []), len(data)

    def _lock(self):
        return nullcontext()

    # A writer refuses a broken ledger; a verifier must still read it in order to report on it.
    def list_keys(self, prefix: str = "") -> list[str]:
        return [k for k in replay(self.ledger_lines()).objects if k.startswith(prefix)]

    def ledger_head(self) -> tuple[int, str]:
        st = replay(self.ledger_lines())
        return st.seq, st.head

    def _write_once(self, *a, **k):
        raise VaultError("the verifier is read-only")

    _ledger_append = _set_retention = _write_once


@dataclass
class RunObjects:
    run_id: str
    run_date: str
    receipt_keys: dict[str, dict] = field(default_factory=dict)   # vault key -> parsed object (or None)
    seal_key: str | None = None
    seal: dict | None = None
    unreadable: list[str] = field(default_factory=list)
    first_seq: int = 0


def _load_json(vault: VaultBackend, key: str):
    data = vault._read(key)
    if data is None:
        return None
    try:
        return json.loads(data)
    except ValueError:
        return None


def runs_in_vault(vault: VaultBackend) -> list[RunObjects]:
    """All runs with at least one receipt or seal, in ledger order. Objects present on disk but missing from
    the ledger are included too (as found), so the ledger check can report them."""
    keys = vault.list_keys("runs/")
    on_disk = [p for p in vault._list_paths() if p.startswith("runs/") and p not in set(keys)]
    runs: dict[str, RunObjects] = {}
    for seq, key in enumerate(keys + on_disk):
        m, s = RECEIPT_RE.match(key), SEAL_RE.match(key)
        if not (m or s):
            continue
        g = (m or s).groupdict()
        run = runs.setdefault(g["run"], RunObjects(g["run"], g["date"], first_seq=seq))
        obj = _load_json(vault, key)
        if obj is None:
            run.unreadable.append(key)
        if m:
            run.receipt_keys[key] = obj
        else:
            run.seal_key, run.seal = key, obj
    return sorted(runs.values(), key=lambda r: r.first_seq)
