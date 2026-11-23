"""Run the full evaluation matrix and write measured results to eval/results/.

  .venv\\Scripts\\python.exe eval\\run_eval.py [--reps 30] [--obs 450] [--seed 20261123]
                                            [--scenarios a,b,...] [--workdir vault-test-eval] [--out eval/results]

For every scenario x repetition it builds one trace (harness.py and scenarios.py), then verifies that trace
under configurations A, B and C with the independent verifier, timing each. Outputs (only measured numbers;
nothing anticipated is written):
  traces.csv            one row per trace x configuration: verdict, first failing step/code, truth step, timings
  confusion.csv         label x verdict counts per configuration, with row totals (denominators)
  per_scenario.csv      verdict counts per scenario and configuration
  metrics.csv           false-assurance rate, precision/recall/F1, false alarms, insufficient recognition,
                        localization accuracy (each with numerator and denominator)
  latency.csv           per-trace verification latency (mean, p95) per configuration, plus context loading
  receipt_timing.csv    per-receipt build time (agent + notary + vault) and per-receipt verify time
  storage.csv           receipt and storage overhead per clean (non-dry) run
  summary.md            the tables above in readable form, with the run environment
Raw traces stay in the workdir (gitignored) for audit.
AI-assisted (Claude). Verified by: tests/test_eval.py (a 1-repetition smoke run of every scenario).
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Trace, attacker_key, build_pool, make_keys, prepare_workdir  # noqa: E402
from metrics import CONFIGS, compute, mean, p95  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

from mwia.common.receipt import verify_signed_object  # noqa: E402
from mwia.verify.engine import MODES, find_run, load_context, verify_run  # noqa: E402
from mwia.verify.reader import RECEIPT_RE, SEAL_RE  # noqa: E402

MODE_OF = {"A": "crypto", "B": "crypto+policy", "C": "crypto+policy+evidence"}


def storage(trace: Trace, rep: dict) -> dict:
    root = trace.vault_root
    sizes = {"receipts": 0, "seal": 0, "raw_responses": 0, "other_evidence": 0, "content_addressed": 0}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        n = p.stat().st_size
        if rel.startswith("objects/"):
            sizes["content_addressed"] += n
        elif RECEIPT_RE.match(rel):
            sizes["receipts"] += n
        elif SEAL_RE.match(rel):
            sizes["seal"] += n
        elif "/evidence/page-" in rel:
            sizes["raw_responses"] += n
        elif "/evidence/" in rel:
            sizes["other_evidence"] += n
    sizes["ledger"] = (root / "LEDGER.jsonl").stat().st_size
    sizes["anchors"] = trace.anchors.stat().st_size if trace.anchors.exists() else 0
    sizes["vault_total"] = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    sizes["receipt_count"] = len(rep["receipts"]) + (1 if rep.get("seal_key") else 0)
    raw = sizes["raw_responses"]
    sizes["overhead_ratio"] = (sizes["vault_total"] - raw) / raw if raw else None
    sizes["integrity_bytes"] = sizes["receipts"] + sizes["seal"] + sizes["ledger"] + sizes["anchors"]
    return sizes


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def fmt(x, pct=False, nd=3):
    if x is None:
        return "n/a"
    return f"{x * 100:.1f}%" if pct else f"{x:.{nd}f}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_eval")
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--obs", type=int, default=450, help="synthetic observations per trace (from the fixtures)")
    ap.add_argument("--seed", type=int, default=20261123)
    ap.add_argument("--scenarios", help="comma-separated subset of scenario names")
    ap.add_argument("--workdir", type=Path, default=ROOT / "vault-test-eval")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results")
    a = ap.parse_args(argv)
    chosen = [s for s in SCENARIOS if not a.scenarios or s.name in a.scenarios.split(",")]
    workdir = prepare_workdir(a.workdir)
    passphrase = secrets.token_hex(16)                      # throwaway; protects only eval keys
    eval_keys, attacker_dir = make_keys(workdir, passphrase)
    ctx = {"attacker": attacker_key(attacker_dir, passphrase)}
    fixtures = json.loads((ROOT / "tests" / "fixtures" / "observations_pool.json").read_text(encoding="utf-8"))["results"]
    pool = build_pool(fixtures, a.obs)
    verifier_cfg = ROOT / "config" / "verifier.yaml"
    rows, builds, verifies, stores = [], [], [], []
    started = time.perf_counter()
    for sc in chosen:
        for rep_i in range(a.reps):
            rng = Random(f"{a.seed}:{sc.name}:{rep_i}")
            trace = Trace(workdir, f"{sc.name}/{rep_i:03d}", pool, eval_keys, passphrase)
            rep, truth_step, variant = sc.build(trace, rng, ctx)
            builds += [dict(t, scenario=sc.name) for t in trace.timings]
            t0 = time.perf_counter()
            vctx = load_context(trace.vault_root, eval_keys / "public", trace.anchors, verifier_cfg)
            load_ms = (time.perf_counter() - t0) * 1000
            run = find_run(vctx, rep["run_id"])
            for cfg in CONFIGS:
                t1 = time.perf_counter()
                v = verify_run(vctx, run, MODE_OF[cfg])
                ms = (time.perf_counter() - t1) * 1000
                ff = v["first_failure"] or {}
                rows.append({"scenario": sc.name, "label": sc.label, "rep": rep_i, "variant": variant,
                             "run_id": rep["run_id"], "config": cfg, "verdict": v["status"],
                             "first_step": ff.get("step"), "first_code": ff.get("code"), "truth_step": truth_step,
                             "verify_ms": round(ms, 3), "load_ms": round(load_ms, 3),
                             "findings": sum(len(x) for x in v["findings"].values())})
            for obj in list(run.receipt_keys.values()) + ([run.seal] if run.seal else []):
                if isinstance(obj, dict):
                    t2 = time.perf_counter()
                    verify_signed_object(obj, vctx.trusted)
                    verifies.append({"scenario": sc.name, "ms": (time.perf_counter() - t2) * 1000})
            if sc.label == "legitimate" and variant == "normal":
                stores.append(dict(storage(trace, rep), scenario=sc.name, rep=rep_i))
        print(f"{sc.name}: {a.reps} trace(s) done ({time.perf_counter() - started:.0f} s)", flush=True)
    elapsed = time.perf_counter() - started

    res = compute(rows)
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "traces.csv", rows)
    write_csv(out / "confusion.csv", [{"config": c, "label": lab, **cnt} for c, m in res["confusion"].items()
                                      for lab, cnt in m.items()])
    write_csv(out / "per_scenario.csv", [{"scenario": s, "config": c, **v} for s, m in res["per_scenario"].items()
                                         for c, v in m.items()])
    write_csv(out / "metrics.csv", [{"config": c, "metric": k, **v} for c, m in res["per_config"].items()
                                    for k, v in m.items()])
    lat = []
    for c in CONFIGS:
        xs = [r["verify_ms"] for r in rows if r["config"] == c]
        lat.append({"measure": f"verify_run config {c}", "n": len(xs), "mean_ms": mean(xs), "p95_ms": p95(xs)})
    loads = [r["load_ms"] for r in rows if r["config"] == "A"]
    lat.append({"measure": "load_context (once per trace)", "n": len(loads), "mean_ms": mean(loads), "p95_ms": p95(loads)})
    tot = [r["load_ms"] + r["verify_ms"] for r in rows if r["config"] == "C"]
    lat.append({"measure": "load_context + verify config C", "n": len(tot), "mean_ms": mean(tot), "p95_ms": p95(tot)})
    write_csv(out / "latency.csv", lat)
    rt = [{"measure": "build per receipt (all steps)", "n": len(builds), "mean_ms": mean([b["ms"] for b in builds]),
           "p95_ms": p95([b["ms"] for b in builds])}]
    for s in range(6):
        xs = [b["ms"] for b in builds if b["step"] == s]
        rt.append({"measure": f"build PR{s}", "n": len(xs), "mean_ms": mean(xs), "p95_ms": p95(xs)})
    vx = [x["ms"] for x in verifies]
    rt.append({"measure": "verify signature + hash per receipt/seal", "n": len(vx), "mean_ms": mean(vx), "p95_ms": p95(vx)})
    write_csv(out / "receipt_timing.csv", rt)
    write_csv(out / "storage.csv", stores)

    # ---- summary.md (measured values only)
    L = []
    L.append("# Evaluation results\n")
    L.append(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `eval/run_eval.py` "
             f"(seed {a.seed}, {a.reps} repetition(s) per scenario, {len(chosen)} scenarios, {a.obs} observations per "
             f"trace; {elapsed:.0f} s wall time). Python {platform.python_version()} on {platform.system()} "
             f"{platform.release()}. Every number below is measured from the traces in `traces.csv`.\n")
    L.append("## Verdicts per scenario (counts out of the repetitions)\n")
    L.append("| Scenario | Label | A: crypto | B: +policy | C: +evidence |\n|---|---|---|---|---|")
    for s in [x.name for x in chosen]:
        m = res["per_scenario"][s]
        cell = lambda c: " ".join(f"{k}={m[c][k]}" for k in ("V", "F", "I") if m[c][k]) + f" / {m[c]['total']}"
        L.append(f"| {s} | {m['A']['label']} | {cell('A')} | {cell('B')} | {cell('C')} |")
    L.append("\nV = VERIFIED WITHIN SCOPE, F = VERIFICATION FAILED, I = INSUFFICIENT EVIDENCE.\n")
    L.append("## Headline metrics\n")
    L.append("| Metric | A: crypto | B: +policy | C: +evidence |\n|---|---|---|---|")
    names = [("false_assurance", "False-assurance rate (non-legitimate traces verified)"),
             ("false_assurance[tampered]", "  of which: tampered"),
             ("false_assurance[policy_violation]", "  of which: policy violation"),
             ("false_assurance[insufficient]", "  of which: insufficient evidence"),
             ("precision", "Violation detection precision"), ("recall", "Violation detection recall"),
             ("f1", "Violation detection F1"), ("false_alarm", "False alarms on legitimate runs"),
             ("insufficient_recognition", "Insufficient-evidence recognition rate"),
             ("localization_accuracy", "Localization accuracy (first failing step)")]
    for key, label in names:
        cells = []
        for c in CONFIGS:
            m = res["per_config"][c][key]
            cells.append(fmt(m["value"], pct=key != "f1") + (f" ({m['numerator']}/{m['denominator']})"
                                                             if m["denominator"] is not None else ""))
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    L.append("\n## Confusion matrices (rows: ground-truth label; row total = denominator)\n")
    for c in CONFIGS:
        L.append(f"**Configuration {c}** ({MODE_OF[c]})\n\n| Label | V | F | I | Total |\n|---|---|---|---|---|")
        for lab, cnt in res["confusion"][c].items():
            L.append(f"| {lab} | {cnt['V']} | {cnt['F']} | {cnt['I']} | {cnt['total']} |")
        L.append("")
    L.append("## Performance\n\n| Measure | n | mean (ms) | p95 (ms) |\n|---|---|---|---|")
    for r in lat + rt:
        L.append(f"| {r['measure']} | {r['n']} | {fmt(r['mean_ms'])} | {fmt(r['p95_ms'])} |")
    if stores:
        L.append("\n## Receipt and storage overhead (clean, non-dry runs)\n\n| Measure | mean | min | max |\n|---|---|---|---|")
        for k in ("receipt_count", "receipts", "seal", "ledger", "anchors", "integrity_bytes", "raw_responses",
                  "other_evidence", "content_addressed", "vault_total", "overhead_ratio"):
            xs = [s[k] for s in stores if s[k] is not None]
            unit = "" if k in ("receipt_count", "overhead_ratio") else " B"
            L.append(f"| {k}{unit} | {fmt(mean(xs), nd=2)} | {fmt(min(xs), nd=2)} | {fmt(max(xs), nd=2)} |")
        L.append("\n`integrity_bytes` = receipts + seal + ledger + anchors. `overhead_ratio` = (vault total − raw "
                 "responses) / raw responses, where the vault total includes the content-addressed copies.")
    L.append("\n## Method notes\n")
    L.append("- Traces come from the real agent pipeline (notary subprocess, local WORM vault, anchors) against an "
             "offline fake of the iNaturalist API (recorded fixtures cloned into synthetic observations) and in-memory "
             "DB stores. MySQL and production data are never touched. Each trace has its own vault.")
    L.append("- Ground-truth labels come from how each trace was generated (`eval/scenarios.py`), never from the "
             "verifier. The truncated-trace label (insufficient) was decided by the author.")
    L.append("- Vault hardening (read-only flags/ACLs) is off for eval traces, so timings exclude `icacls` calls. "
             "Hardening itself is tested in `tests/test_vault_local.py`.")
    L.append("- Build time per receipt covers body construction, module measurement, the notary round trip and the "
             "vault write. Verify latency covers one `verify_run` call. `load_context` (reading the vault, ledger "
             "check, anchors, keys) runs once per trace and is reported separately.")
    L.append("\n## Threats to validity\n")
    L.append("- The scenario generators and the verifier were written by the same (AI-assisted) developer, with the "
             "scenario table known in advance. The results show that the verifier meets its specification on these "
             "attack constructions. They are not evidence of robustness against attacks outside them.")
    L.append("- The verifier was corrected once because of this evaluation: the first full run (archived in "
             "`eval/results/archive/run1-before-decision-list-fix/`) showed omitted decision lists being reported "
             "as policy failures. That run's numbers are kept for the record.")
    L.append("- Repetitions vary the manipulated object, step and parameters (seeded), but all traces share one "
             "synthetic observation pool, one machine and an offline API. Live API behaviour (latency, errors, "
             "late indexing) isn't part of these measurements.")
    L.append("- The timings are from a single Windows 11 workstation with hardening off, so treat them as relative.")
    (out / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"done in {elapsed:.0f} s; results in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
