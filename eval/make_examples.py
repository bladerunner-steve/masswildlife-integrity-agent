"""Build the publishable example badges and pages in examples/ from synthetic runs only.

It uses the evaluation harness: offline fake API over synthetic clones of the fixtures, in-memory DB, a
throwaway notary key made in a temporary directory, and a temporary vault. Nothing touches MySQL, iNaturalist,
the production vault or the production key. It writes:
  examples/verified/        a clean run, configuration C (green)
  examples/failed/          a signed but unauthorized run (place_id added), configuration C (red)
  examples/false-assurance/ the same unauthorized run under configuration A (crypto only): green, wrongly
  examples/insufficient/    a run whose PR2 omitted a raw page, configuration C (amber)
Each folder holds badge.svg, index.html and verdict.json. The temporary data is deleted afterwards.
Usage: .venv\\Scripts\\python.exe eval\\make_examples.py
AI-assisted (Claude). Verified by: tests/test_eval.py (examples contain no local paths or real identifiers).
"""
from __future__ import annotations

import json
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Trace, build_pool, make_keys, prepare_workdir  # noqa: E402
from scenarios import omitted_evidence  # noqa: E402

from mwia.verify.engine import find_run, load_context, verify_run  # noqa: E402
from mwia.verify.report import write_run_report  # noqa: E402


def main(out: Path = ROOT / "examples") -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mwia-examples-"))
    try:
        work = prepare_workdir(tmp / "work")
        pw = secrets.token_hex(16)
        keys, _ = make_keys(work, pw)
        fixtures = json.loads((ROOT / "tests" / "fixtures" / "observations_pool.json").read_text(encoding="utf-8"))["results"]
        pool = build_pool(fixtures, 450)
        cfg = ROOT / "config" / "verifier.yaml"

        def verdict(trace, rep, mode):
            ctx = load_context(trace.vault_root, keys / "public", trace.anchors, cfg)
            return verify_run(ctx, find_run(ctx, rep["run_id"]), mode)

        made = {}
        t = Trace(work, "verified", pool, keys, pw)
        made["verified"] = verdict(t, t.run(), "crypto+policy+evidence")
        t = Trace(work, "failed", pool, keys, pw)
        rep = t.run("--unsafe-bypass-gate", "--unsafe-param", "place_id=1")
        made["failed"] = verdict(t, rep, "crypto+policy+evidence")
        made["false-assurance"] = verdict(t, rep, "crypto")
        t = Trace(work, "insufficient", pool, keys, pw)
        rng = Random(7)
        while True:  # pick the raw-page variant for a clear example
            state = rng.getstate()
            if rng.choice(["raw_page", "raw_page", "decision_list", "db_readback", "reconciliation"]) == "raw_page":
                rng.setstate(state)
                break
        rep, _, _ = omitted_evidence(t, rng, {})
        made["insufficient"] = verdict(t, rep, "crypto+policy+evidence")
        for name, v in made.items():
            d = out / name
            if d.exists():
                shutil.rmtree(d)
            write_run_report(v, d)
            print(f"{name:16s} config {v['config']}  {v['status']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
