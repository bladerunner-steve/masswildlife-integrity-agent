"""`agent run`: one complete, receipted ingest run (M0 -> M5, seal, anchor, report).

Flags: --dry-run (no DB writes at all: the observation DB is SELECT-only, and neither run state nor the
provenance index is written, but every step is still receipted, sealed and anchored), --vault prod|test,
--db prod|test, --window-hours N (overrides the incremental window; the policy gate still applies).
Eval only: --unsafe-bypass-gate [--unsafe-param k=v ...] requires --vault test AND --db test.
Window: [last successful window_end - overlap, now], capped at max_hours + grace. An uncovered gap is
flagged, not silently absorbed. First run: [now - 24 h, now]. Only one run at a time (OS file lock).
Exit codes: 0 success; 1 partial or flagged; 2 failed or policy violation; 3 usage/config error;
4 another run in progress.
At the end, the independent verifier (configuration C) checks the run, writes its badge and pages, and records
the verdict in provenance_index (UPDATE). A red verdict means exit 2 and an amber one at least exit 1.
AI-assisted (Claude). Verified by: tests/test_pipeline.py (offline end-to-end with recorded fixtures) and
the Checkpoint 3 live runs.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import dotenv_values

from mwia.common.canonical import ZERO_HASH
from mwia.common.filelock import LockTimeout, file_lock
from mwia.index.db import ALLOWED, connect
from mwia.notary.client import NotaryClient
from mwia.vault import open_vault
from mwia.index.provenance import update_verification
from mwia.vault.anchor import AnchorLog

from . import auth as auth_mod
from . import config as config_mod
from . import m0_plan, m1_request, m2_response, m3_filter, m4_db, m5_complete
from .emit import RunContext, latest_seal_hash
from .http import InatClient
from .store import ObservationStore, RunStateStore

EXIT = {"success": 0, "flagged": 1, "partial": 1, "failed": 2, "usage": 3, "locked": 4}


class UsageError(Exception):
    pass


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_window(now: datetime, policy: dict, overlap_min: int, last_end: datetime | None,
                   override_hours: float | None) -> dict:
    cap = timedelta(hours=policy["window"]["max_hours"], minutes=policy["window"]["grace_minutes"])
    if override_hours is not None:
        return {"start": iso(now - timedelta(hours=override_hours)), "end": iso(now), "field": "created_at",
                "source": "override", "gap_seconds": None}
    if last_end is None:
        return {"start": iso(now - timedelta(hours=policy["window"]["max_hours"])), "end": iso(now),
                "field": "created_at", "source": "first_run", "gap_seconds": None}
    last_end = last_end.replace(tzinfo=timezone.utc) if last_end.tzinfo is None else last_end
    earliest = now - cap
    start = max(last_end - timedelta(minutes=overlap_min), earliest)
    gap = int((earliest - last_end).total_seconds()) if earliest > last_end else None
    return {"start": iso(start), "end": iso(now), "field": "created_at", "source": "run_state", "gap_seconds": gap}


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="agent run", description="One receipted iNaturalist ingest run.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--vault", choices=["prod", "test"], default="prod")
    ap.add_argument("--db", choices=["prod", "test"], default="prod")
    ap.add_argument("--window-hours", type=float)
    ap.add_argument("--unsafe-bypass-gate", action="store_true", help="EVALUATION ONLY (test vault + test DB)")
    ap.add_argument("--unsafe-param", action="append", default=[], metavar="KEY=VALUE",
                    help="EVALUATION ONLY: add/override a request parameter (KEY= removes it)")
    a = ap.parse_args(argv)
    if a.unsafe_bypass_gate and not (a.vault == "test" and a.db == "test"):
        raise UsageError("--unsafe-bypass-gate requires --vault test and --db test")
    if a.unsafe_param and not a.unsafe_bypass_gate:
        raise UsageError("--unsafe-param requires --unsafe-bypass-gate")
    if a.window_hours is not None and a.window_hours <= 0:
        raise UsageError("--window-hours must be positive")
    a.overrides = {}
    for kv in a.unsafe_param:
        if "=" not in kv:
            raise UsageError(f"--unsafe-param expects KEY=VALUE, got {kv!r}")
        k, v = kv.split("=", 1)
        a.overrides[k] = v if v != "" else None
    return a


class Deps:
    """External dependencies, replaceable in tests: DB stores, HTTP session, notary, clock."""

    def __init__(self, cfg, args):
        self.cfg, self.args = cfg, args
        self.env_file = cfg.root / ".env"
        self._conns = []

    def now(self) -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)

    def token(self) -> str | None:
        return dotenv_values(self.env_file).get("INAT_API_TOKEN") or None

    def stores(self, table: str):
        obs_db = connect(self.env_file, allowed=("SELECT",) if self.args.dry_run else ALLOWED)
        meta_db = connect(self.env_file, allowed=("SELECT",) if self.args.dry_run else ALLOWED)
        self._conns += [obs_db, meta_db]
        return ObservationStore(obs_db, table), RunStateStore(meta_db), (None if self.args.dry_run else meta_db)

    def http_client(self, token):
        s = self.cfg.settings["agent"]
        rl = self.cfg.policy["rate_limit"]
        return InatClient(rl["user_agent"], rl["max_requests_per_minute"], token=token,
                          timeout=s["http_timeout_seconds"], max_attempts=s["http_max_attempts"])

    def notary(self):
        return NotaryClient(self.cfg.root / self.cfg.settings["agent"]["keys_dir"], env_file=self.env_file)

    def trusted_keys_dir(self) -> Path:
        return self.cfg.root / self.cfg.settings["agent"]["keys_dir"] / "public"

    def verify(self, env: str, run_id: str) -> dict:
        from mwia.verify.__main__ import verify_and_report
        s = self.cfg.settings
        return verify_and_report(self.cfg.data_root / s["vault"]["roots"][env],
                                 self.cfg.data_root / s["anchors"]["files"][env], self.trusted_keys_dir(),
                                 self.cfg.data_root / s["agent"]["reports_dir"], run_id=run_id,
                                 verifier_cfg=self.cfg.root / "config" / "verifier.yaml")[0]

    def anchor_log(self, env: str) -> AnchorLog:
        a = self.cfg.settings["anchors"]
        return AnchorLog(self.cfg.data_root / a["files"][env], git=a.get("git", True), git_executable=a.get("git_executable"))

    def close(self) -> None:
        for c in self._conns:
            try:
                c.close()
            except Exception:
                pass


def _alert(cfg, line: str) -> None:
    p = cfg.data_root / cfg.settings["agent"]["reports_dir"] / "ALERTS.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with open(p, "a", encoding="utf-8") as f:
        if new:
            f.write("# Alerts\n\nOne line per flagged, partial or failed run (newest last).\n\n")
        f.write(line + "\n")


def execute(args, cfg, deps: Deps) -> tuple[int, dict]:
    settings, policy = cfg.settings, cfg.policy
    now = deps.now()
    auth = auth_mod.resolve(deps.token(), now, policy["auth"]["min_token_validity_minutes"],
                            policy["auth"]["allow_anonymous"])
    table = settings["database"]["tables"][args.db]
    obs_store, run_state, index_db = deps.stores(table)
    last_end = None if args.window_hours is not None else run_state.last_success_end(args.db)
    window = compute_window(now, policy, settings["agent"]["window_overlap_minutes"], last_end, args.window_hours)
    vault = open_vault(settings, args.vault, cfg.data_root)
    prev_seal = latest_seal_hash(vault) or ZERO_HASH
    run_id = str(uuid.uuid4())
    report = {"run_id": run_id, "started_at": iso(now), "vault": args.vault, "db": args.db, "db_table": table,
              "dry_run": args.dry_run, "window": window, "auth_mode": auth["auth_mode"], "auth_reason": auth["reason"],
              "token_warning": auth["warning"], "unsafe_bypass_gate": args.unsafe_bypass_gate,
              "unsafe_params": sorted(args.overrides)}
    notary = deps.notary().start()
    ctx = RunContext(cfg, run_id, now.strftime("%Y-%m-%d"), args.vault, args.db, args.dry_run, vault, notary,
                     index_db, prev_hash=prev_seal)
    recon, seal = None, None
    try:
        plan = m0_plan.run(ctx, window, {"dry_run": args.dry_run, "vault": args.vault, "db": args.db,
                                         "db_table": table, "window_hours": args.window_hours})
        if not args.dry_run:
            run_state.start(run_id, args.db, args.dry_run, _naive(window["start"]), _naive(window["end"]),
                            window["gap_seconds"], now.replace(tzinfo=None), prev_seal)
        client = deps.http_client(deps.token() if auth["auth_mode"] == "token" else None)
        m1 = m1_request.run(ctx, plan, auth, client.public_headers(), args.overrides, args.unsafe_bypass_gate)
        m2 = m3 = m4 = None
        if m1["send"]:
            m2 = m2_response.run(ctx, plan, m1, client, args.unsafe_bypass_gate)
            m3 = m3_filter.run(ctx, plan, m2["observations"], obs_store)
            m4 = m4_db.run(ctx, m3, obs_store, table)
        recon = m5_complete.run(ctx, plan, m1, m2, m3, m4, auth)
        seal, seal_key = ctx.seal()
        head = vault.ledger_head()
        anchor = deps.anchor_log(args.vault).append(run_id, seal["seal_hash"], *head)
        report.update(seal_hash=seal["seal_hash"], seal_key=seal_key, anchor=anchor)
    except Exception as e:
        report["error"] = f"{type(e).__name__}: {e}"
        report["truncated_trace"] = seal is None
    finally:
        notary.close()
    status = recon["status"] if recon and "error" not in report else "failed"
    report.update(status=status, reconciliation=recon, receipts=[
        {"step": r["body"]["step"], "module": r["body"]["module"], "receipt_hash": r["receipt_hash"],
         "policy_decision": r["body"]["policy_decision"], "key": k} for r, k in zip(ctx.receipts, ctx.receipt_keys)],
        log=ctx.log, finished_at=iso(deps.now()))
    flags = (recon or {}).get("flags", [])
    code = EXIT[status] if status != "success" else (EXIT["flagged"] if flags else 0)
    # Independent 3-layer verification (configuration C) of the run just written, plus badge and pages.
    verdict_status = None
    try:
        v = deps.verify(args.vault, run_id)
        verdict_status = v["status"]
        report["verification"] = {k: v.get(k) for k in ("status", "config", "mode", "first_failure", "report")}
        if index_db is not None:
            update_verification(index_db, run_id, v["status"], v["mode"])
    except Exception as e:
        report["verification_error"] = f"{type(e).__name__}: {e}"
    if verdict_status == "VERIFICATION FAILED" or "verification_error" in report:
        code = max(code, EXIT["failed"])
    elif verdict_status == "INSUFFICIENT EVIDENCE":
        code = max(code, EXIT["flagged"])
    # Run state, which decides the next window, is written only after verification. A window counts as covered
    # ("success") only if the run succeeded AND the verifier did not find it red or amber. Otherwise the next
    # run re-reads that period (within the 24 h + grace cap).
    state_status = status
    if verdict_status == "VERIFICATION FAILED" or "verification_error" in report:
        state_status = "failed"
    elif verdict_status == "INSUFFICIENT EVIDENCE" and status == "success":
        state_status = "partial"
    report["run_state_status"] = state_status
    if not args.dry_run:
        try:
            run_state.finish(run_id, state_status, deps.now().replace(tzinfo=None), seal["seal_hash"] if seal else None)
        except Exception as e:
            report["run_state_error"] = f"{type(e).__name__}: {e}"
    if code:
        reason = "; ".join((recon or {}).get("reasons", []) + flags + ([report["error"]] if "error" in report else [])
                           + ([f"verifier: {verdict_status}"] if verdict_status not in (None, "VERIFIED WITHIN SCOPE")
                              else []) + ([report["verification_error"]] if "verification_error" in report else []))
        _alert(cfg, f"- {report['finished_at']} run `{run_id}` vault={args.vault} db={args.db} "
                    f"status={status.upper()}: {reason or 'see report'}")
    out = cfg.data_root / settings["agent"]["reports_dir"] / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    report["report_path"] = str(out / "report.json")
    report["exit_code"] = code
    return code, report


def _naive(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def print_summary(rep: dict) -> None:
    r = rep.get("reconciliation") or {}
    c = r.get("counts", {})
    print(f"run {rep['run_id']}  vault={rep['vault']} db={rep['db']}({rep['db_table']}) dry_run={rep['dry_run']}")
    print(f"window {rep['window']['start']} -> {rep['window']['end']} ({rep['window']['source']})  auth={rep['auth_mode']}")
    for line in rep.get("log", []):
        print("  " + line)
    if c:
        print(f"counts: total_results={c.get('total_results')} fetched={c.get('fetched')} accepted={c.get('accepted')} "
              f"rejected={c.get('rejected')} inserted={c.get('inserted')} updated={c.get('updated')} "
              f"skipped={c.get('skipped')}")
    for ch in r.get("checks", []):
        print(f"  check {ch['name']}: {'ok' if ch['ok'] else 'FAIL'} {ch['detail']}")
    for f in r.get("flags", []):
        print(f"  FLAG {f}")
    if rep.get("token_warning"):
        print(f"  WARNING {rep['token_warning']}")
    if rep.get("error"):
        print(f"  ERROR {rep['error']}")
    ver = rep.get("verification")
    if ver:
        ff = ver.get("first_failure")
        print(f"VERIFIER (config {ver['config']}): {ver['status']}"
              + (f" - step {ff.get('step', '-')} {ff.get('module', '')}: {ff['message']}" if ff else ""))
        if ver.get("report"):
            print(f"badge: {ver['report']['page']}")
    elif rep.get("verification_error"):
        print(f"VERIFIER ERROR {rep['verification_error']}")
    print(f"STATUS {rep['status'].upper()}  seal={rep.get('seal_hash', '-')[:16]}  exit={rep['exit_code']}")
    print(f"report: {rep['report_path']}")


def main(argv: list[str] | None = None, deps_factory=Deps, cfg=None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except UsageError as e:
        print(f"agent run: {e}", file=sys.stderr)
        return EXIT["usage"]
    cfg = cfg or config_mod.load()
    deps = deps_factory(cfg, args)
    try:
        with file_lock(cfg.data_root / ".mwia-agent.lock", timeout=1.0):
            code, rep = execute(args, cfg, deps)
    except LockTimeout:
        print("agent run: another run is in progress", file=sys.stderr)
        return EXIT["locked"]
    except auth_mod.AuthError as e:
        print(f"agent run: {e}", file=sys.stderr)
        return EXIT["failed"]
    except Exception as e:  # setup failed before any receipt (DB down, vault/notary unavailable, ...)
        print(f"agent run: could not start: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT["failed"]
    finally:
        deps.close()
    print_summary(rep)
    return code
