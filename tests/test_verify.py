"""Verifier tests (mwia.verify): each case produces a run with the real pipeline (offline world from
test_pipeline), then either tampers with the vault afterwards or alters what the agent signs. Expected
statuses per configuration here are test expectations; the verifier itself contains no expected outcomes.
AI-assisted (Claude)."""
import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mwia.agent.emit import RunContext
from mwia.common.canonical import hash_obj, jcs, sha256_hex
from mwia.notary.keys import keygen, load_active_private_key
from mwia.verify.__main__ import main as verify_main
from mwia.verify.engine import FAILED, INSUFFICIENT, MODES, VERIFIED, find_run, load_context, verify_run
from mwia.verify.report import badge_svg, write_index, write_run_report

from conftest import TEST_PASSPHRASE, force_writable, unharden_tree
from test_pipeline import TEST, World
from test_agent_units import jwt

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def world(tmp_path, keys_dir):
    w = World(tmp_path, keys_dir)
    yield w
    unharden_tree(tmp_path / "data")


def vroot(world, env="test"):
    return world.cfg.data_root / world.cfg.settings["vault"]["roots"][env]


def anchors(world, env="test"):
    return world.cfg.data_root / world.cfg.settings["anchors"]["files"][env]


def verify(world, run_id=None, mode="crypto+policy+evidence"):
    ctx = load_context(vroot(world), world.keys_dir / "public", anchors(world), REPO / "config" / "verifier.yaml")
    return verify_run(ctx, find_run(ctx, run_id), mode)


def by_mode(world, run_id=None):
    return tuple(verify(world, run_id, m)["status"] for m in MODES)


def codes(v, layer=None):
    return {f["code"] for L, fs in v["findings"].items() if layer in (None, L) for f in fs}


def run_ok(world, *argv):
    world.run(*TEST, *argv)
    return world.last_report()


def receipt_path(world, rep, step):
    return vroot(world) / next(r["key"] for r in rep["receipts"] if r["step"] == step)


def write_obj(path: Path, obj) -> None:
    force_writable(path)
    path.write_bytes(jcs(obj))


V, F, I = VERIFIED, FAILED, INSUFFICIENT


# ---------------- legitimate runs ----------------

def test_clean_run_verified_in_every_configuration(world):
    rep = run_ok(world)
    assert by_mode(world) == (V, V, V)
    v = verify(world)
    assert all(s[L] == "pass" for s in v["steps"] for L in "ABC") and v["first_failure"] is None
    assert v["config"] == "C" and v["sealed"]


def test_dry_run_and_chained_second_run_verified(world):
    run_ok(world, "--dry-run")
    from datetime import timedelta
    world.now += timedelta(hours=1)
    run_ok(world)
    ctx = load_context(vroot(world), world.keys_dir / "public", anchors(world), REPO / "config" / "verifier.yaml")
    assert [verify_run(ctx, r)["status"] for r in ctx.runs] == [V, V]


# ---------------- tampering after the fact (A must fail) ----------------

def _page2(world, rep):
    pr2 = json.loads(receipt_path(world, rep, 2).read_bytes())
    ev = next(e for e in pr2["body"]["evidence"] if e["key"].endswith("page-0002.json"))
    return pr2, ev


def test_naive_artifact_tamper(world):
    rep = run_ok(world)
    _, ev = _page2(world, rep)
    p = vroot(world) / ev["key"]
    force_writable(p)
    p.write_bytes(p.read_bytes().replace(b'"results"', b'"results" ', 1))
    assert by_mode(world) == (F, F, F)
    v = verify(world)
    assert "evidence_hash_mismatch" in codes(v, "A") and v["first_failure"]["step"] == 2


def test_log_rewriting(world):
    rep = run_ok(world)
    pr2, ev = _page2(world, rep)
    p = vroot(world) / ev["key"]
    force_writable(p)
    p.write_bytes(b'{"total_results":0,"results":[]}')
    ev["sha256"] = sha256_hex(p.read_bytes())               # the attacker also rewrites the recorded hash...
    pr2["receipt_hash"] = hash_obj(pr2["body"])             # ...and recomputes the receipt hash, but can't re-sign
    write_obj(receipt_path(world, rep, 2), pr2)
    assert by_mode(world) == (F, F, F)
    assert {"bad_signature"} <= codes(verify(world), "A")


def _resign(world, rep, from_step, key, kid):
    prev = None
    for s in range(6):
        path = receipt_path(world, rep, s)
        obj = json.loads(path.read_bytes())
        if s >= from_step:
            b = obj["body"]
            b["notary_key_id"] = kid
            if prev is not None:
                b["prev_hash"] = prev
            obj = {"body": b, "receipt_hash": hash_obj(b), "signature": key.sign(jcs(b)).hex()}
            write_obj(path, obj)
        prev = obj["receipt_hash"]


@pytest.mark.parametrize("from_step", [2, 0], ids=["forward_recompute", "key_forgery"])
def test_resigned_with_untrusted_key(world, tmp_path, from_step):
    rep = run_ok(world)
    keygen(tmp_path / "attacker", TEST_PASSPHRASE)
    key, kid = load_active_private_key(tmp_path / "attacker", TEST_PASSPHRASE)
    _resign(world, rep, from_step, key, kid)
    assert by_mode(world) == (F, F, F)
    assert "untrusted_key" in codes(verify(world), "A")


def test_replayed_receipt_from_another_run(world):
    first = run_ok(world)
    from datetime import timedelta
    world.now += timedelta(hours=1)
    second = run_ok(world)
    old_pr3 = json.loads(receipt_path(world, first, 3).read_bytes())
    write_obj(receipt_path(world, second, 3), old_pr3)
    assert by_mode(world, second["run_id"]) == (F, F, F)
    assert {"receipt_misplaced", "replayed_receipt"} <= codes(verify(world, second["run_id"]), "A")


def test_anchor_mismatch(world):
    run_ok(world)
    with open(anchors(world), "ab") as f:
        f.write(jcs({"time": "2026-11-23T06:00:00Z", "run_id": "x", "seal_hash": "f" * 64, "ledger_seq": 0,
                     "ledger_head": "0" * 64}) + b"\n")
    assert by_mode(world) == (F, F, F)
    assert "anchor_mismatch" in codes(verify(world), "A")


# ---------------- validly signed but wrong (B or C must catch it; A cannot) ----------------

def test_signed_but_unauthorized_request(world):
    world.run(*TEST, "--unsafe-bypass-gate", "--unsafe-param", "place_id=999")
    assert by_mode(world) == (V, F, F)                       # crypto-only gives false assurance
    v = verify(world)
    assert "request_forbidden_param" in codes(v, "B") and v["first_failure"]["step"] == 1


def test_window_over_24h_signed(world):
    world.run(*TEST, "--unsafe-bypass-gate", "--window-hours", "30")
    assert by_mode(world) == (V, F, F)
    assert {"window_too_long", "request_window"} <= codes(verify(world), "B")


def test_gate_blocked_run_is_red(world):
    world.run(*TEST, "--window-hours", "30")
    v = verify(world)
    assert v["status"] == F and {"agent_recorded_violation", "plan_deviation"} <= codes(v, "B")


def _patch_emit(monkeypatch, fn):
    orig = RunContext.emit

    def emit(self, step, module, **kw):
        r = fn(self, step, module, kw)
        return r if r is not None else orig(self, step, module, **kw)

    monkeypatch.setattr(RunContext, "emit", emit)


def test_plan_deviation_skipped_step(world, monkeypatch):
    _patch_emit(monkeypatch, lambda ctx, step, module, kw: {"receipt_hash": ctx.prev_hash} if step == 3 else None)
    world.run(*TEST)
    assert by_mode(world) == (V, F, F)
    assert "plan_deviation" in codes(verify(world), "B")


def test_omitted_raw_page(world, monkeypatch):
    def drop(ctx, step, module, kw):
        if step == 2:
            kw["evidence"] = [e for e in kw["evidence"] if not e["key"].endswith("page-0002.json")]
    _patch_emit(monkeypatch, drop)
    world.run(*TEST)
    assert by_mode(world) == (V, V, I)
    assert "raw_page_missing" in codes(verify(world), "C")


@pytest.mark.parametrize("role,step", [("decision_list", 3), ("db_readback", 4), ("reconciliation", 5)])
def test_omitted_mandatory_evidence_is_insufficient_not_failed(world, monkeypatch, role, step):
    """Regression: with the decision list omitted, layer B used to report every written record as
    'unaccepted' (FAILED). Missing evidence must give INSUFFICIENT, which only layer C reports."""
    def drop(ctx, s, module, kw):
        if s == step:
            kw["evidence"] = [e for e in kw["evidence"] if e["role"] != role]
    _patch_emit(monkeypatch, drop)
    world.run(*TEST)
    assert by_mode(world) == (V, V, I)
    assert "mandatory_evidence_missing" in codes(verify(world), "C")


def test_unreconcilable_counts(world, monkeypatch):
    def inflate(ctx, step, module, kw):
        if step == 4:
            kw["payload"] = dict(kw["payload"], inserted=kw["payload"]["inserted"] + 5)
    _patch_emit(monkeypatch, inflate)
    world.run(*TEST)
    assert by_mode(world) == (V, V, I)
    assert "counts_unreconciled" in codes(verify(world), "C")


def test_truncated_trace_without_seal(world, monkeypatch):
    def crash(self):
        raise RuntimeError("process died before sealing")
    monkeypatch.setattr(RunContext, "seal", crash)
    world.run(*TEST)
    v = verify(world)
    assert "seal_missing" in codes(v, "A") and v["status"] == I   # label per config/verifier.yaml (Phase 5 decision)


# ---------------- report, badge, token banner ----------------

def test_badge_colours_and_labels():
    for status, colour in ((V, "#1e7b34"), (F, "#b3261e"), (I, "#b26a00")):
        svg = badge_svg(status, "C")
        assert colour in svg and status in svg and "configuration C" in svg and "http" not in svg.replace(
            "http://www.w3.org/2000/svg", "")


def test_pages_have_scope_statement_and_no_external_requests(world, tmp_path):
    world.token = jwt(world.now.replace(year=2025))          # expired token -> anonymous + banner
    rep = run_ok(world)
    page = Path(rep["verification"]["report"]["page"]).read_text(encoding="utf-8")
    assert "does not attest that the observations" in page and "Token needs refresh" in page
    assert "VERIFIED WITHIN SCOPE" in page and "src=\"http" not in page and "href=\"http" not in page
    index = (world.cfg.data_root / "reports" / "index.html").read_text(encoding="utf-8")
    assert rep["run_id"][:8] in index


def test_failure_page_localizes_the_problem(world):
    world.run(*TEST, "--unsafe-bypass-gate", "--unsafe-param", "place_id=999")
    v = verify(world)
    out = write_run_report(v, world.cfg.data_root / "reports" / "runs" / v["run_id"])
    page = Path(out["page"]).read_text(encoding="utf-8")
    assert "Where it went wrong" in page and "Step 1" in page and "location or scope parameter" in page


# ---------------- independence, read-only, CLI ----------------

def test_verifier_imports_no_agent_or_database_code():
    for f in (REPO / "src" / "mwia" / "verify").glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
                [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        for name in names:
            assert not name.startswith(("mwia.agent", "mwia.index", "pymysql")), (f.name, name)
            assert not name.startswith((".agent", "..agent", "..index")), (f.name, name)


def test_verifier_process_loads_no_agent_or_db_modules(world):
    run_ok(world)
    code = ("import sys, json; from mwia.verify.__main__ import main; "
            f"rc = main(['--vault-dir', r'{vroot(world)}', '--anchors', r'{anchors(world)}', '--keys', "
            f"r'{world.keys_dir / 'public'}', '--no-report', '--json']); "
            "bad = [m for m in sys.modules if m.startswith(('mwia.agent', 'mwia.index', 'pymysql'))]; "
            "print('BAD', bad); sys.exit(rc)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**__import__("os").environ, "PYTHONPATH": str(REPO / "src")})
    assert r.returncode == 0, r.stderr
    assert "BAD []" in r.stdout and json.loads(r.stdout[:r.stdout.rindex("BAD")])["status"] == V


def test_verifier_is_read_only(world):
    run_ok(world)
    root = vroot(world)
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    lock_mtime = (root / ".lock").stat().st_mtime
    for m in MODES:
        verify(world, mode=m)
    after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after and (root / ".lock").stat().st_mtime == lock_mtime


def test_cli_exit_codes_and_json(world, capsys):
    rep = run_ok(world)
    args = ["--vault-dir", str(vroot(world)), "--anchors", str(anchors(world)), "--keys",
            str(world.keys_dir / "public"), "--no-report"]
    capsys.readouterr()  # drop the run summary printed by `agent run`
    assert verify_main(args + ["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_id"] == rep["run_id"]
    _, ev = _page2(world, rep)
    p = vroot(world) / ev["key"]
    force_writable(p)
    p.write_bytes(b"{}")
    assert verify_main(args) == 2
    assert verify_main(args + ["--mode", "crypto", "--run", "no-such-run"]) == 3
