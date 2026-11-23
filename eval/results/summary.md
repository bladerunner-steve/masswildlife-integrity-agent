# Evaluation results

Generated 2026-11-23 20:21 UTC by `eval/run_eval.py` (seed 20261123, 30 repetition(s) per scenario, 12 scenarios, 450 observations per trace; 232 s wall time). Python 3.14.6 on Windows 11. Every number below is measured from the traces in `traces.csv`.

## Verdicts per scenario (counts out of the repetitions)

| Scenario | Label | A: crypto | B: +policy | C: +evidence |
|---|---|---|---|---|
| clean_authorized_run | legitimate | V=30 / 30 | V=30 / 30 | V=30 / 30 |
| naive_artifact_tamper | tampered | F=30 / 30 | F=30 / 30 | F=30 / 30 |
| log_rewriting | tampered | F=30 / 30 | F=30 / 30 | F=30 / 30 |
| forward_recompute | tampered | F=30 / 30 | F=30 / 30 | F=30 / 30 |
| key_forgery | tampered | F=30 / 30 | F=30 / 30 | F=30 / 30 |
| signed_but_unauthorized | policy_violation | V=30 / 30 | F=30 / 30 | F=30 / 30 |
| plan_deviation | policy_violation | V=30 / 30 | F=30 / 30 | F=30 / 30 |
| window_over_24h | policy_violation | V=30 / 30 | F=30 / 30 | F=30 / 30 |
| omitted_evidence | insufficient | V=30 / 30 | V=30 / 30 | I=30 / 30 |
| unreconcilable_counts | insufficient | V=30 / 30 | V=30 / 30 | I=30 / 30 |
| truncated_trace | insufficient | I=30 / 30 | I=30 / 30 | I=30 / 30 |
| replayed_receipt | tampered | F=30 / 30 | F=30 / 30 | F=30 / 30 |

V = VERIFIED WITHIN SCOPE, F = VERIFICATION FAILED, I = INSUFFICIENT EVIDENCE.

## Headline metrics

| Metric | A: crypto | B: +policy | C: +evidence |
|---|---|---|---|
| False-assurance rate (non-legitimate traces verified) | 45.5% (150/330) | 18.2% (60/330) | 0.0% (0/330) |
|   of which: tampered | 0.0% (0/150) | 0.0% (0/150) | 0.0% (0/150) |
|   of which: policy violation | 100.0% (90/90) | 0.0% (0/90) | 0.0% (0/90) |
|   of which: insufficient evidence | 66.7% (60/90) | 66.7% (60/90) | 0.0% (0/90) |
| Violation detection precision | 100.0% (150/150) | 100.0% (240/240) | 100.0% (240/240) |
| Violation detection recall | 62.5% (150/240) | 100.0% (240/240) | 100.0% (240/240) |
| Violation detection F1 | 0.769 | 1.000 | 1.000 |
| False alarms on legitimate runs | 0.0% (0/30) | 0.0% (0/30) | 0.0% (0/30) |
| Insufficient-evidence recognition rate | 33.3% (30/90) | 33.3% (30/90) | 100.0% (90/90) |
| Localization accuracy (first failing step) | 100.0% (150/150) | 100.0% (240/240) | 100.0% (240/240) |

## Confusion matrices (rows: ground-truth label; row total = denominator)

**Configuration A** (crypto)

| Label | V | F | I | Total |
|---|---|---|---|---|
| legitimate | 30 | 0 | 0 | 30 |
| tampered | 0 | 150 | 0 | 150 |
| policy_violation | 90 | 0 | 0 | 90 |
| insufficient | 60 | 0 | 30 | 90 |

**Configuration B** (crypto+policy)

| Label | V | F | I | Total |
|---|---|---|---|---|
| legitimate | 30 | 0 | 0 | 30 |
| tampered | 0 | 150 | 0 | 150 |
| policy_violation | 0 | 90 | 0 | 90 |
| insufficient | 60 | 0 | 30 | 90 |

**Configuration C** (crypto+policy+evidence)

| Label | V | F | I | Total |
|---|---|---|---|---|
| legitimate | 30 | 0 | 0 | 30 |
| tampered | 0 | 150 | 0 | 150 |
| policy_violation | 0 | 90 | 0 | 90 |
| insufficient | 0 | 0 | 90 | 90 |

## Performance

| Measure | n | mean (ms) | p95 (ms) |
|---|---|---|---|
| verify_run config A | 360 | 5.315 | 6.111 |
| verify_run config B | 360 | 15.489 | 19.285 |
| verify_run config C | 360 | 24.448 | 32.326 |
| load_context (once per trace) | 360 | 18.621 | 28.882 |
| load_context + verify config C | 360 | 43.070 | 51.393 |
| build per receipt (all steps) | 2276 | 30.951 | 34.122 |
| build PR0 | 390 | 32.584 | 33.817 |
| build PR1 | 390 | 30.741 | 31.602 |
| build PR2 | 390 | 30.539 | 32.744 |
| build PR3 | 379 | 30.100 | 34.983 |
| build PR4 | 367 | 30.543 | 33.890 |
| build PR5 | 360 | 31.169 | 34.686 |
| verify signature + hash per receipt/seal | 2403 | 0.268 | 0.624 |

## Receipt and storage overhead (clean, non-dry runs)

| Measure | mean | min | max |
|---|---|---|---|
| receipt_count | 7.00 | 7.00 | 7.00 |
| receipts B | 21077.95 | 21075.00 | 21081.00 |
| seal B | 681.00 | 681.00 | 681.00 |
| ledger B | 6295.00 | 6295.00 | 6295.00 |
| anchors B | 263.00 | 263.00 | 263.00 |
| integrity_bytes B | 28316.95 | 28314.00 | 28320.00 |
| raw_responses B | 734543.00 | 734543.00 | 734543.00 |
| other_evidence B | 851282.95 | 851280.00 | 851286.00 |
| content_addressed B | 1607584.89 | 1607579.00 | 1607591.00 |
| vault_total B | 3221604.79 | 3221593.00 | 3221617.00 |
| overhead_ratio | 3.39 | 3.39 | 3.39 |

`integrity_bytes` = receipts + seal + ledger + anchors. `overhead_ratio` = (vault total − raw responses) / raw responses, where the vault total includes the content-addressed copies.

## Method notes

- Traces come from the real agent pipeline (notary subprocess, local WORM vault, anchors) against an offline fake of the iNaturalist API (recorded fixtures cloned into synthetic observations) and in-memory DB stores. MySQL and production data are never touched. Each trace has its own vault.
- Ground-truth labels come from how each trace was generated (`eval/scenarios.py`), never from the verifier. The truncated-trace label (insufficient) was decided by the author.
- Vault hardening (read-only flags/ACLs) is off for eval traces, so timings exclude `icacls` calls. Hardening itself is tested in `tests/test_vault_local.py`.
- Build time per receipt covers body construction, module measurement, the notary round trip and the vault write. Verify latency covers one `verify_run` call. `load_context` (reading the vault, ledger check, anchors, keys) runs once per trace and is reported separately.

## Threats to validity

- The scenario generators and the verifier were written by the same (AI-assisted) developer, with the scenario table known in advance. The results show that the verifier meets its specification on these attack constructions. They are not evidence of robustness against attacks outside them.
- The verifier was corrected once because of this evaluation: the first full run (archived in `eval/results/archive/run1-before-decision-list-fix/`) showed omitted decision lists being reported as policy failures. That run's numbers are kept for the record.
- Repetitions vary the manipulated object, step and parameters (seeded), but all traces share one synthetic observation pool, one machine and an offline API. Live API behaviour (latency, errors, late indexing) isn't part of these measurements.
- The timings are from a single Windows 11 workstation with hardening off, so treat them as relative.
