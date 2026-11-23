# Evaluation results

Generated 2026-11-23 19:50 UTC by `eval/run_eval.py` (seed 20261123, 30 repetition(s) per scenario, 12 scenarios, 450 observations per trace; 248 s wall time). Python 3.14.6 on Windows 11. Every number below is measured from the traces in `traces.csv`.

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
| omitted_evidence | insufficient | V=30 / 30 | V=22 F=8 / 30 | F=8 I=22 / 30 |
| unreconcilable_counts | insufficient | V=30 / 30 | V=30 / 30 | I=30 / 30 |
| truncated_trace | insufficient | I=30 / 30 | I=30 / 30 | I=30 / 30 |
| replayed_receipt | tampered | F=30 / 30 | F=30 / 30 | F=30 / 30 |

V = VERIFIED WITHIN SCOPE, F = VERIFICATION FAILED, I = INSUFFICIENT EVIDENCE.

## Headline metrics

| Metric | A: crypto | B: +policy | C: +evidence |
|---|---|---|---|
| False-assurance rate (non-legitimate traces verified) | 45.5% (150/330) | 15.8% (52/330) | 0.0% (0/330) |
|   of which: tampered | 0.0% (0/150) | 0.0% (0/150) | 0.0% (0/150) |
|   of which: policy violation | 100.0% (90/90) | 0.0% (0/90) | 0.0% (0/90) |
|   of which: insufficient evidence | 66.7% (60/90) | 57.8% (52/90) | 0.0% (0/90) |
| Violation detection precision | 100.0% (150/150) | 96.8% (240/248) | 96.8% (240/248) |
| Violation detection recall | 62.5% (150/240) | 100.0% (240/240) | 100.0% (240/240) |
| Violation detection F1 | 0.769 | 0.984 | 0.984 |
| False alarms on legitimate runs | 0.0% (0/30) | 0.0% (0/30) | 0.0% (0/30) |
| Insufficient-evidence recognition rate | 33.3% (30/90) | 33.3% (30/90) | 91.1% (82/90) |
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
| insufficient | 52 | 8 | 30 | 90 |

**Configuration C** (crypto+policy+evidence)

| Label | V | F | I | Total |
|---|---|---|---|---|
| legitimate | 30 | 0 | 0 | 30 |
| tampered | 0 | 150 | 0 | 150 |
| policy_violation | 0 | 90 | 0 | 90 |
| insufficient | 0 | 8 | 82 | 90 |

## Performance

| Measure | n | mean (ms) | p95 (ms) |
|---|---|---|---|
| verify_run config A | 360 | 5.692 | 7.175 |
| verify_run config B | 360 | 16.656 | 21.501 |
| verify_run config C | 360 | 26.102 | 38.591 |
| load_context (once per trace) | 360 | 19.719 | 28.799 |
| load_context + verify config C | 360 | 45.820 | 58.444 |
| build per receipt (all steps) | 2276 | 33.867 | 44.339 |
| build PR0 | 390 | 35.483 | 44.006 |
| build PR1 | 390 | 32.852 | 38.656 |
| build PR2 | 390 | 33.806 | 46.333 |
| build PR3 | 379 | 33.786 | 46.561 |
| build PR4 | 367 | 33.552 | 44.608 |
| build PR5 | 360 | 33.689 | 41.253 |
| verify signature + hash per receipt/seal | 2403 | 0.286 | 0.646 |

## Receipt and storage overhead (clean, non-dry runs)

| Measure | mean | min | max |
|---|---|---|---|
| receipt_count | 7.00 | 7.00 | 7.00 |
| receipts B | 21079.63 | 21077.00 | 21081.00 |
| seal B | 681.00 | 681.00 | 681.00 |
| ledger B | 6295.00 | 6295.00 | 6295.00 |
| anchors B | 263.00 | 263.00 | 263.00 |
| integrity_bytes B | 28318.63 | 28316.00 | 28320.00 |
| raw_responses B | 735893.00 | 735893.00 | 735893.00 |
| other_evidence B | 853984.63 | 853982.00 | 853986.00 |
| content_addressed B | 1611638.26 | 1611633.00 | 1611641.00 |
| vault_total B | 3229711.53 | 3229701.00 | 3229717.00 |
| overhead_ratio | 3.39 | 3.39 | 3.39 |

`integrity_bytes` = receipts + seal + ledger + anchors. `overhead_ratio` = (vault total − raw responses) / raw responses, where the vault total includes the content-addressed copies.

## Method notes

- Traces come from the real agent pipeline (notary subprocess, local WORM vault, anchors) against an offline fake of the iNaturalist API (recorded fixtures cloned into synthetic observations) and in-memory DB stores. MySQL and production data are never touched. Each trace has its own vault.
- Ground-truth labels come from how each trace was generated (`eval/scenarios.py`), never from the verifier. The truncated-trace label (insufficient) was decided by the author.
- Vault hardening (read-only flags/ACLs) is off for eval traces, so timings exclude `icacls` calls. Hardening itself is tested in `tests/test_vault_local.py`.
- Build time per receipt covers body construction, module measurement, the notary round trip and the vault write. Verify latency covers one `verify_run` call. `load_context` (reading the vault, ledger check, anchors, keys) runs once per trace and is reported separately.
