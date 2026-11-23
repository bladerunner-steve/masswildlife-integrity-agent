"""Offline end-to-end tests of `agent run` (mwia.agent.pipeline).

Real pieces: notary subprocess (throwaway key), hardened LocalWormVault, anchors, receipts, measurements.
Fakes: the iNaturalist API (served from tests/fixtures/observations_pool.json with keyset pagination) and the
two DB stores (same interface as mwia.agent.store). The policy is a copy of config/policy.yaml with
per_page=3, so the 10 fixture records span 4 pages. AI-assisted (Claude)."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import yaml

from mwia.agent import config as config_mod
from mwia.agent import pipeline
from mwia.agent.http import InatClient
from mwia.agent.transform import differs, to_row
from mwia.common.canonical import ZERO_HASH, hash_obj
from mwia.common.filelock import file_lock
from mwia.common.keyring import load_trusted_keys
from mwia.common.receipt import verify_signed_object
from mwia.common.timeutil import parse_utc
from mwia.notary.client import NotaryClient
from mwia.vault.anchor import AnchorLog, check_anchors
from mwia.vault.local import LocalWormVault

from conftest import TEST_PASSPHRASE, unharden_tree

REPO = Path(__file__).resolve().parents[1]
POOL = json.loads((REPO / "tests" / "fixtures" / "observations_pool.json").read_text(encoding="utf-8"))["results"]
T0 = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)


class Resp:
    def __init__(self, status, body, url):
        self.status_code, self.content, self.url, self.headers = status, body, url, {}


class FakeInat:
    """Keyset-paginated fake of GET /v2/observations over a pool of observations."""

    def __init__(self, pool):
        self.pool = copy.deepcopy(pool)
        self.calls, self.fail_calls = [], set()

    def get(self, url, params, headers, timeout):
        self.calls.append({"params": dict(params), "headers": dict(headers)})
        if len(self.calls) in self.fail_calls:
            return Resp(503, b"", url)
        d1, d2 = parse_utc(params["created_d1"]), parse_utc(params["created_d2"])
        res = []
        for o in self.pool:
            if getattr(self, "ignore_window", False) or d1 <= datetime.fromisoformat(o["created_at"]) <= d2:
                o = copy.deepcopy(o)
                if "place_id" in params:  # a different place: records outside the pinned scope place
                    o["place_ids"] = [int(params["place_id"])]
                res.append(o)
        if "id_above" in params:
            res = [o for o in res if o["id"] > int(params["id_above"])]
        res.sort(key=lambda o: o["id"])
        n = int(params["per_page"])
        body = {"total_results": len(res), "page": 1, "per_page": n, "results": res[:n]}
        return Resp(200, json.dumps(body).encode(), requests.Request("GET", url, params=params).prepare().url)


class FakeObsStore:
    user = "claude"

    def __init__(self, allowed=("SELECT", "INSERT", "UPDATE")):
        self.rows, self.ops_used, self.allowed = {}, set(), allowed

    def fetch(self, ids):
        self.ops_used.add("SELECT")
        return {i: dict(self.rows[i]) for i in ids if i in self.rows}

    def upsert(self, rows):
        assert "INSERT" in self.allowed, "dry run must not write"
        self.ops_used.add("INSERT")
        out = []
        for r in rows:
            if r["id"] not in self.rows:
                out.append(1)
            elif differs(r, self.rows[r["id"]]):
                out.append(2)
            else:
                out.append(0)
            self.rows[r["id"]] = dict(r)
        return out

    def readback(self, ids):
        self.ops_used.add("SELECT")
        return [dict(self.rows[i]) for i in sorted(ids) if i in self.rows]


class FakeRunState:
    def __init__(self):
        self.rows = {}

    def last_success_end(self, env):
        ends = [r["end"] for r in self.rows.values() if r["env"] == env and r["status"] == "success" and not r["dry"]]
        return max(ends) if ends else None

    def start(self, run_id, env, dry_run, start, end, gap, started_at, prev_seal):
        assert not dry_run
        self.rows[run_id] = {"env": env, "dry": dry_run, "start": start, "end": end, "status": "running", "gap": gap}

    def finish(self, run_id, status, finished_at, seal_hash):
        self.rows[run_id].update(status=status, seal=seal_hash)


class World:
    def __init__(self, tmp, keys_dir):
        self.tmp, self.keys_dir = tmp, keys_dir
        self.inat = FakeInat(POOL)
        self.obs = FakeObsStore()
        self.state = FakeRunState()
        self.now = T0
        self.token = None
        policy =yaml.safe_load((REPO / "config" / "policy.yaml").read_text(encoding="utf-8"))
        policy["rate_limit"]["per_page"] = 3
        self.policy_path = tmp / "policy.yaml"
        self.policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
        self.cfg = config_mod.load(REPO, policy_path=self.policy_path, data_root=tmp / "data")

    def deps(self):
        world = self

        class TestDeps(pipeline.Deps):
            def now(self):
                return world.now

            def stores(self, table):
                world.obs.ops_used = set()
                world.obs.allowed = ("SELECT",) if self.args.dry_run else ("SELECT", "INSERT", "UPDATE")
                return world.obs, world.state, None

            def http_client(self, token):
                return InatClient("masswildlife-integrity-agent/0.1", 6000, token=token, session=world.inat,
                                  sleep=lambda s: None, wall=lambda: world.now + timedelta(seconds=1))

            def notary(self):
                return NotaryClient(world.keys_dir, env_file=world.tmp / "none.env",
                                    extra_env={"NOTARY_KEY_PASSPHRASE": TEST_PASSPHRASE})

            def anchor_log(self, env):
                return AnchorLog(world.cfg.data_root / world.cfg.settings["anchors"]["files"][env], git=False)

            def trusted_keys_dir(self):
                return world.keys_dir / "public"

            def token(self):
                return world.token

        return TestDeps

    def run(self, *argv):
        return pipeline.main(list(argv), deps_factory=self.deps(), cfg=self.cfg)

    def vault(self, env="test"):
        return LocalWormVault(self.cfg.data_root / self.cfg.settings["vault"]["roots"][env])

    def last_report(self):
        runs = sorted((self.cfg.data_root / "reports" / "runs").glob("*/report.json"), key=lambda p: p.stat().st_mtime)
        return json.loads(runs[-1].read_text(encoding="utf-8"))

    def receipts(self, rep, env="test"):
        v = self.vault(env)
        return [json.loads(v.get(r["key"])) for r in rep["receipts"]], json.loads(v.get(rep["seal_key"]))


@pytest.fixture
def world(tmp_path, keys_dir):
    w = World(tmp_path, keys_dir)
    yield w
    unharden_tree(tmp_path / "data")


TEST = ("--vault", "test", "--db", "test")


def test_full_run(world, keys_dir):
    assert world.run(*TEST) == 0
    rep = world.last_report()
    rs, seal = world.receipts(rep)
    trusted = load_trusted_keys(keys_dir / "public")
    assert [r["body"]["step"] for r in rs] == [0, 1, 2, 3, 4, 5]
    assert all(verify_signed_object(o, trusted) == [] for o in rs + [seal])
    assert rs[0]["body"]["prev_hash"] == ZERO_HASH and seal["body"]["receipt_count"] == 6
    plan = rs[0]["body"]["payload"]
    vault = world.vault()
    for prev, cur in zip(rs, rs[1:]):
        b = cur["body"]
        assert b["prev_hash"] == prev["receipt_hash"] and b["spec_hash"] == rs[0]["receipt_hash"]
        assert b["in_hash"] == prev["body"]["out_hash"]                         # data chain
    for r in rs:
        b = r["body"]
        assert b["agent_id"] == plan["expected_measurements"][b["module"]]      # measured == declared
        for ev in b["evidence"]:
            assert vault.head(ev["key"]).sha256 == ev["sha256"]
    # out_hash equals the primary evidence object's hash, so the verifier can recompute it
    for step, role in ((3, "decision_list"), (4, "db_readback"), (5, "reconciliation")):
        ev = next(e for e in rs[step]["body"]["evidence"] if e["role"] == role)
        assert ev["sha256"] == rs[step]["body"]["out_hash"]
    pr2 = rs[2]["body"]["payload"]
    assert pr2["page_count"] == 4 and pr2["fetched"] == 10 and pr2["total_results"] == 10
    assert [p["results"] for p in pr2["pages"]] == [3, 3, 3, 1]
    assert [p["params"].get("id_above") for p in pr2["pages"]][1:] == [pr2["pages"][i]["last_id"] for i in range(3)]
    assert rs[3]["body"]["payload"]["counts"]["accepted"] == {"new": 10, "changed": 0, "unchanged": 0}
    pr4 = rs[4]["body"]["payload"]
    assert (pr4["inserted"], pr4["updated"], pr4["skipped"], pr4["committed"]) == (10, 0, 0, True)
    assert pr4["operations_used"] == ["INSERT", "SELECT"] and pr4["db_user"] == "claude"
    assert rs[4]["body"]["policy_decision"] == "pass"
    assert sorted(world.obs.rows) == sorted(o["id"] for o in POOL)
    assert all("Authorization" not in c["headers"] for c in world.inat.calls)
    assert rep["status"] == "success"
    assert rep["verification"]["status"] == "VERIFIED WITHIN SCOPE" and rep["verification"]["config"] == "C"
    assert Path(rep["verification"]["report"]["badge"]).is_file()
    assert list(world.state.rows.values())[0]["status"] == "success"
    fields = rs[1]["body"]["payload"]["request"]["params"]["fields"]
    assert "private_geojson" not in fields and "private_location" not in fields and "private_place_guess" not in fields
    assert all("Authorization" not in json.dumps(r["body"]) for r in rs)


def test_rerun_is_idempotent_and_chained(world):
    assert world.run(*TEST) == 0
    first = world.last_report()
    world.now = T0 + timedelta(hours=1)
    assert world.run(*TEST) == 0
    rep = world.last_report()
    rs, _ = world.receipts(rep)
    assert rs[0]["body"]["prev_hash"] == first["seal_hash"]          # runs chain through seals
    w = rs[0]["body"]["payload"]["window"]
    assert w["source"] == "run_state" and w["start"] == "2026-11-23T04:50:00Z"   # last end - 10 min overlap
    world.inat.ignore_window = True  # re-serve all records regardless of window for the next run
    world.now = T0 + timedelta(hours=2)
    assert world.run(*TEST) == 1                                     # flagged: records outside the window
    rs, _ = world.receipts(world.last_report())
    counts = rs[3]["body"]["payload"]["counts"]
    assert counts["rejected"]["outside_window"] == 10 and rs[4]["body"]["payload"]["inserted"] == 0


def test_unchanged_and_changed_records(world):
    assert world.run(*TEST) == 0
    world.now = T0 + timedelta(minutes=5)
    assert world.run(*TEST, "--window-hours", "24") == 0
    rs, _ = world.receipts(world.last_report())
    assert rs[3]["body"]["payload"]["counts"]["accepted"] == {"new": 0, "changed": 0, "unchanged": 10}
    assert rs[4]["body"]["payload"]["skipped"] == 10
    target = POOL[4]["id"]
    world.obs.rows[target]["quality_grade"] = "casual"                # row edited since the last run
    world.now = T0 + timedelta(minutes=10)
    assert world.run(*TEST, "--window-hours", "24") == 0
    rs, _ = world.receipts(world.last_report())
    assert rs[3]["body"]["payload"]["counts"]["accepted"] == {"new": 0, "changed": 1, "unchanged": 9}
    assert (rs[4]["body"]["payload"]["updated"], rs[4]["body"]["payload"]["skipped"]) == (1, 9)
    assert world.obs.rows[target]["quality_grade"] == to_row(POOL[4])["quality_grade"]


def test_gate_violation_skips_fetch_and_fails(world):
    assert world.run(*TEST, "--window-hours", "30") == 2
    rep = world.last_report()
    rs, seal = world.receipts(rep)
    assert [r["body"]["step"] for r in rs] == [0, 1, 5] and seal["body"]["receipt_count"] == 3
    assert rs[1]["body"]["policy_decision"] == "violation"
    assert rs[1]["body"]["payload"]["gate"]["violations"] == ["win.max_length"]
    assert world.inat.calls == [] and world.obs.rows == {}
    assert rep["status"] == "failed" and list(world.state.rows.values())[0]["status"] == "failed"
    alerts = (world.cfg.data_root / "reports" / "ALERTS.md").read_text(encoding="utf-8")
    assert rep["run_id"] in alerts and "policy_gate_violation" in alerts


@pytest.mark.parametrize("argv", [["--unsafe-bypass-gate"], ["--unsafe-bypass-gate", "--vault", "test"],
                                  ["--unsafe-bypass-gate", "--db", "test"], [*TEST, "--unsafe-param", "place_id=1"],
                                  ["--window-hours", "0"]])
def test_usage_errors(world, argv):
    assert world.run(*argv) == 3
    assert world.inat.calls == []


def test_bypass_sends_unauthorized_request_but_scope_check_rejects(world):
    assert world.run(*TEST, "--unsafe-bypass-gate", "--unsafe-param", "place_id=999") == 2  # verifier: red
    rs, _ = world.receipts(world.last_report())
    assert rs[1]["body"]["policy_decision"] == "pass"                         # the simulated compromised gate
    assert rs[1]["body"]["payload"]["request"]["params"]["place_id"] == "999"  # ...but the evidence is recorded
    assert world.inat.calls[0]["params"]["place_id"] == "999"
    c = rs[3]["body"]["payload"]["counts"]
    assert c["rejected"]["out_of_policy_scope"] == 10 and rs[3]["body"]["policy_decision"] == "violation"
    assert world.obs.rows == {}
    # a red run must not count as covering its window: the next run starts from the previous good window
    rep = world.last_report()
    assert rep["status"] == "success" and rep["run_state_status"] == "failed"
    assert world.state.last_success_end("test") is None


def test_dry_run_writes_nothing_but_is_receipted(world):
    assert world.run(*TEST, "--dry-run") == 0
    rep = world.last_report()
    rs, seal = world.receipts(rep)
    pr4 = rs[4]["body"]["payload"]
    assert pr4["dry_run"] and pr4["operations_used"] == ["SELECT"] and pr4["inserted"] == 0 and pr4["skipped"] == 10
    assert world.obs.rows == {} and world.state.rows == {}
    assert len(rs) == 6 and seal["body"]["receipt_count"] == 6


def test_failed_page_makes_run_partial(world):
    world.inat.fail_calls = {2, 3, 4, 5, 6}                         # page 2 fails on every retry
    assert world.run(*TEST) == 1
    rep = world.last_report()
    assert rep["status"] == "partial"
    chk = {c["name"]: c["ok"] for c in rep["reconciliation"]["checks"]}
    assert chk["pages_complete"] is False and chk["fetched_eq_decided"] is True
    rs, _ = world.receipts(rep)
    assert rs[2]["body"]["payload"]["error"]["page"] == 2 and rs[4]["body"]["payload"]["inserted"] == 3


def test_duplicate_record_in_response(world):
    world.inat.pool.append(copy.deepcopy(world.inat.pool[0]))       # the API returns one record twice
    assert world.run(*TEST) == 0
    rs, _ = world.receipts(world.last_report())
    c = rs[3]["body"]["payload"]["counts"]
    assert c["rejected"]["duplicate_in_response"] == 1 and c["fetched"] == 11 and c["accepted"]["new"] == 10


def test_overlapping_run_refused(world):
    world.cfg.data_root.mkdir(parents=True, exist_ok=True)
    with file_lock(world.cfg.data_root / ".mwia-agent.lock"):
        assert world.run(*TEST) == 4
    assert world.inat.calls == []
