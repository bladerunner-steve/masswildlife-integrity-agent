"""`verify` CLI (read-only): python scripts/mwia.py verify [options]

  --vault prod|test        which vault from config/settings.yaml (default prod), or --vault-dir PATH
  --run RUN_ID | --all     one run (default: the latest) or every run in the vault
  --mode crypto | crypto+policy | crypto+policy+evidence   configuration A / B / C (default C)
  --json                   print machine-readable verdict(s) for the evaluation harness
  --no-report              don't write badge.svg / index.html / verdict.json
  --anchors PATH, --keys PATH, --reports-dir PATH   override the trust inputs and output location
Exit codes: 0 VERIFIED WITHIN SCOPE, 1 INSUFFICIENT EVIDENCE, 2 VERIFICATION FAILED, 3 usage/input error.
It writes only under the reports directory. It never writes to the vault, keys or anchors.
AI-assisted (Claude). Verified by: tests/test_verify.py (CLI exit codes and JSON).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .engine import FAILED, INSUFFICIENT, MODES, find_run, load_context, verify_run

ROOT = Path(__file__).resolve().parents[3]
EXIT = {"VERIFIED WITHIN SCOPE": 0, INSUFFICIENT: 1, FAILED: 2}


def verify_and_report(vault_dir: Path, anchors: Path | None, keys: Path, reports_dir: Path | None,
                      run_id: str | None = None, mode: str = "crypto+policy+evidence", all_runs: bool = False,
                      verifier_cfg: Path = ROOT / "config" / "verifier.yaml") -> list[dict]:
    ctx = load_context(vault_dir, keys, anchors, verifier_cfg)
    runs = ctx.runs if all_runs else [find_run(ctx, run_id)]
    verdicts = [verify_run(ctx, r, mode) for r in runs]
    if reports_dir is not None:
        from .report import write_index, write_run_report
        for v in verdicts:
            v["report"] = write_run_report(v, Path(reports_dir) / "runs" / v["run_id"])
        write_index(reports_dir)
    return verdicts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verify")
    ap.add_argument("--vault", choices=["prod", "test"], default="prod")
    ap.add_argument("--vault-dir", type=Path)
    ap.add_argument("--run")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--mode", choices=list(MODES), default="crypto+policy+evidence")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--anchors", type=Path)
    ap.add_argument("--keys", type=Path, default=ROOT / "keys" / "public")
    ap.add_argument("--reports-dir", type=Path)
    a = ap.parse_args(argv)
    settings = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    vault_dir = a.vault_dir or ROOT / settings["vault"]["roots"][a.vault]
    anchors = a.anchors or ROOT / settings["anchors"]["files"][a.vault]
    reports = None if a.no_report else (a.reports_dir or ROOT / settings["agent"]["reports_dir"])
    try:
        verdicts = verify_and_report(vault_dir, anchors, a.keys, reports, a.run, a.mode, a.all)
    except (LookupError, OSError, ValueError) as e:
        print(f"verify: {e}", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps(verdicts if a.all else verdicts[0], indent=2))
    else:
        for v in verdicts:
            ff = v["first_failure"]
            where = f" at step {ff.get('step', '-')} {ff.get('module', '')}: {ff['message']}" if ff else ""
            n = sum(len(f) for f in v["findings"].values())
            print(f"{v['run_id']}  config {v['config']}  {v['status']}{where}  ({n} finding(s))")
            if "report" in v:
                print(f"  report: {v['report']['page']}")
    return max(EXIT[v["status"]] for v in verdicts)


if __name__ == "__main__":
    sys.exit(main())
