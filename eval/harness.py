"""Evaluation harness: runs the real agent pipeline offline to produce one trace per (scenario, repetition).

Each trace gets its own directory: its own test vault, anchors and reports. Isolation matters because a
ledger break in a shared vault would affect every run in it. What is real and what is faked:
  real: agent pipeline M0-M5, notary subprocess (a throwaway eval key, never the production key), local
        WORM vault (hardening off for speed; hardening is covered by tests/test_vault_local.py), anchors,
        receipts, measurements, verifier
  fake: the iNaturalist API (recorded fixtures plus synthetic clones, served with keyset pagination) and
        the DB stores (in memory, same interface as mwia.agent.store), so MySQL is never touched
Safety: the harness always passes --vault test --db test, refuses a workdir that is or contains the
production vault, anchors or keys, and only clears a workdir that carries its .mwia-eval marker.
AI-assisted (Claude). Verified by: tests/test_eval.py (harness smoke test and scenario labels).
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from mwia.agent import config as config_mod
from mwia.agent import pipeline
from mwia.agent.emit import RunContext
from mwia.agent.http import InatClient
from mwia.agent.transform import differs
from mwia.common.canonical import hash_obj, jcs
from mwia.common import merkle
from mwia.common.timeutil import parse_utc
from mwia.notary.client import NotaryClient
from mwia.notary.keys import keygen, load_active_private_key
from mwia.vault.anchor import AnchorLog

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)
MARKER = ".mwia-eval"
SCOPE = 141552


# ---------------- synthetic observation pool ----------------

def build_pool(fixtures: list[dict], n: int, end: datetime = T0) -> list[dict]:
    """n observations: the recorded fixtures cloned with new ids and uuids, and created_at spread over
    [end - 23 h, end - 5 min]. Everything else (taxa, photos, place_ids) is the real recorded content."""
    out = []
    span = timedelta(hours=23) - timedelta(minutes=5)
    for i in range(n):
        o = copy.deepcopy(fixtures[i % len(fixtures)])
        o["id"] = 500_000_000 + i
        o["uuid"] = str(uuid.UUID(int=i + 1))
        created = end - timedelta(hours=23) + span * (i / max(1, n - 1))
        o["created_at"] = created.astimezone(timezone(timedelta(hours=-5))).isoformat(timespec="seconds")
        out.append(o)
    return out


class FakeInat:
    """Keyset-paginated fake of GET /v2/observations. Requests that change the scope (another project, a
    place or location filter, a user filter) get records from outside the pinned place."""

    def __init__(self, pool):
        self.pool = pool
        self.calls = 0

    def get(self, url, params, headers, timeout):
        self.calls += 1
        d1, d2 = parse_utc(params["created_d1"]), parse_utc(params["created_d2"])
        other = str(params.get("project_id")) != "46777" or any(
            k in params for k in ("place_id", "lat", "lng", "radius", "nelat", "swlat", "user_id"))
        res = []
        for o in self.pool:
            if d1 <= datetime.fromisoformat(o["created_at"]) <= d2:
                if other:
                    o = dict(o, place_ids=[1, 2])
                res.append(o)
        if "id_above" in params:
            res = [o for o in res if o["id"] > int(params["id_above"])]
        n = int(params["per_page"])
        body = json.dumps({"total_results": len(res), "page": 1, "per_page": n, "results": res[:n]}).encode()
        r = requests.models.Response()
        r.status_code, r._content = 200, body
        r.url = requests.Request("GET", url, params=params).prepare().url
        return r


class FakeObsStore:
    user = "claude"

    def __init__(self):
        self.rows, self.ops_used, self.allowed = {}, set(), ("SELECT", "INSERT", "UPDATE")

    def fetch(self, ids):
        self.ops_used.add("SELECT")
        return {i: dict(self.rows[i]) for i in ids if i in self.rows}

    def upsert(self, rows):
        if "INSERT" not in self.allowed:
            raise RuntimeError("dry run must not write")
        self.ops_used.add("INSERT")
        out = []
        for r in rows:
            out.append(1 if r["id"] not in self.rows else (2 if differs(r, self.rows[r["id"]]) else 0))
            self.rows[r["id"]] = dict(r)
        return out

    def readback(self, ids):
        self.ops_used.add("SELECT")
        return [dict(self.rows[i]) for i in sorted(ids) if i in self.rows]


class FakeRunState:
    def __init__(self):
        self.rows = {}

    def last_success_end(self, env):
        ends = [r["end"] for r in self.rows.values() if r["status"] == "success"]
        return max(ends) if ends else None

    def start(self, run_id, env, dry_run, start, end, gap, started_at, prev_seal):
        self.rows[run_id] = {"end": end, "status": "running"}

    def finish(self, run_id, status, finished_at, seal_hash):
        self.rows[run_id]["status"] = status


# ---------------- emit patching and timing ----------------

@contextlib.contextmanager
def patched_emit(deviation=None, timings: list | None = None):
    """deviation(ctx, step, module, kw, orig) may change kw in place, or return a value to skip the normal
    emit. Build time per receipt (body construction, measurement, notary signature, vault write) goes into
    `timings`."""
    orig = RunContext.emit

    def emit(self, step, module, **kw):
        t = time.perf_counter()
        r = deviation(self, step, module, kw, orig) if deviation else None
        if r is None:
            r = orig(self, step, module, **kw)
        if timings is not None:
            timings.append({"step": step, "ms": (time.perf_counter() - t) * 1000})
        return r

    RunContext.emit = emit
    try:
        yield
    finally:
        RunContext.emit = orig


# ---------------- one trace ----------------

class Trace:
    def __init__(self, workdir: Path, name: str, pool: list[dict], eval_keys: Path, passphrase: str):
        self.dir = Path(workdir) / name
        self.dir.mkdir(parents=True)
        self.inat, self.obs, self.state = FakeInat(pool), FakeObsStore(), FakeRunState()
        self.now = T0
        self.keys, self.passphrase = eval_keys, passphrase
        self.cfg = config_mod.load(REPO, data_root=self.dir)
        self.cfg.settings["vault"]["harden"] = False
        self.timings: list[dict] = []

    @property
    def vault_root(self) -> Path:
        return self.dir / self.cfg.settings["vault"]["roots"]["test"]

    @property
    def anchors(self) -> Path:
        return self.dir / self.cfg.settings["anchors"]["files"]["test"]

    def _deps(self):
        tr = self

        class EvalDeps(pipeline.Deps):
            def now(self):
                return tr.now

            def token(self):
                return None

            def stores(self, table):
                tr.obs.ops_used = set()
                tr.obs.allowed = ("SELECT",) if self.args.dry_run else ("SELECT", "INSERT", "UPDATE")
                return tr.obs, tr.state, None

            def http_client(self, token):
                return InatClient("masswildlife-integrity-agent/0.1", 6000, session=tr.inat, sleep=lambda s: None,
                                  wall=lambda: tr.now + timedelta(seconds=2))

            def notary(self):
                return NotaryClient(tr.keys, env_file=tr.dir / "none.env",
                                    extra_env={"NOTARY_KEY_PASSPHRASE": tr.passphrase})

            def anchor_log(self, env):
                return AnchorLog(tr.anchors, git=False)

            def trusted_keys_dir(self):
                return tr.keys / "public"

            def verify(self, env, run_id):  # the harness verifies after any post-run manipulation
                return {"status": None, "config": "-", "mode": "-"}

        return EvalDeps

    def run(self, *argv, deviation=None) -> dict:
        before = set((self.dir / "reports" / "runs").glob("*")) if (self.dir / "reports" / "runs").exists() else set()
        with patched_emit(deviation, self.timings), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            code = pipeline.main(["--vault", "test", "--db", "test", *argv], deps_factory=self._deps(), cfg=self.cfg)
        new = sorted(set((self.dir / "reports" / "runs").glob("*")) - before)
        rep = json.loads((new[-1] / "report.json").read_text(encoding="utf-8"))
        rep["exit_code"] = code
        return rep

    # ---- post-run manipulation helpers (the "attacker" with write access to the vault) ----
    def key_of(self, rep: dict, step: int) -> Path:
        return self.vault_root / next(r["key"] for r in rep["receipts"] if r["step"] == step)

    def read(self, path: Path) -> dict:
        return json.loads(path.read_bytes())

    def write(self, path: Path, obj) -> None:
        path.write_bytes(jcs(obj) if not isinstance(obj, (bytes, bytearray)) else bytes(obj))

    def resign(self, rep: dict, from_step: int, key, kid: str) -> None:
        """Re-sign receipts from `from_step` on, and the seal, with `key` (a key the verifier doesn't trust),
        recomputing prev_hash links, spec_hash, the Merkle root and the seal, as a forward-recompute attacker would."""
        steps = sorted(r["step"] for r in rep["receipts"])
        prev, spec, hashes = None, None, []
        for s in steps:
            path = self.key_of(rep, s)
            obj = self.read(path)
            b = obj["body"]
            if s >= from_step:
                b["notary_key_id"] = kid
                if prev is not None:
                    b["prev_hash"] = prev
                if s != 0 and spec is not None:
                    b["spec_hash"] = spec
                obj = {"body": b, "receipt_hash": hash_obj(b), "signature": key.sign(jcs(b)).hex()}
                self.write(path, obj)
            prev = obj["receipt_hash"]
            spec = obj["receipt_hash"] if s == 0 else spec
            hashes.append(prev)
        if rep.get("seal_key"):
            sp = self.vault_root / rep["seal_key"]
            sb = self.read(sp)["body"]
            sb.update(merkle_root=merkle.root_hex(hashes), head_hash=hashes[-1], notary_key_id=kid)
            self.write(sp, {"body": sb, "seal_hash": hash_obj(sb), "signature": key.sign(jcs(sb)).hex()})


def prepare_workdir(workdir: Path, fresh: bool = True) -> Path:
    workdir = Path(workdir).resolve()
    repo = REPO.resolve()
    if workdir == repo or workdir in repo.parents:
        raise SystemExit(f"refusing eval workdir {workdir}: it contains the repository")
    # Never inside, equal to, or around the production vault/anchors/keys or the real test vault.
    for f in (repo / "vault", repo / "anchors", repo / "keys", repo / "vault-test", repo / "anchors-test"):
        f = f.resolve()
        if workdir == f or f in workdir.parents or workdir in f.parents:
            raise SystemExit(f"refusing eval workdir {workdir}: it overlaps {f}")
    if workdir.exists():
        if not (workdir / MARKER).exists():
            raise SystemExit(f"refusing to clear {workdir}: it has no {MARKER} marker")
        if fresh:
            shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / MARKER).write_text("evaluation scratch area; safe to delete\n", encoding="utf-8")
    return workdir


def make_keys(workdir: Path, passphrase: str) -> tuple[Path, Path]:
    """A throwaway trusted eval key, plus an attacker key the verifier will not trust."""
    trusted, attacker = workdir / "eval-keys", workdir / "attacker-keys"
    keygen(trusted, passphrase)
    keygen(attacker, passphrase)
    return trusted, attacker


def attacker_key(attacker_dir: Path, passphrase: str):
    return load_active_private_key(attacker_dir, passphrase)
