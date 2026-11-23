"""Tests for the evaluation harness (eval/): scenario construction, workdir safety, and the metric code against a
hand-computed example. AI-assisted (Claude)."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval"))

import harness  # noqa: E402
import metrics  # noqa: E402
from run_eval import main as run_eval  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

V, F, I = metrics.V, metrics.F, metrics.I


def test_every_scenario_builds_once_and_has_a_valid_label(tmp_path):
    out = tmp_path / "results"
    assert run_eval(["--reps", "1", "--obs", "30", "--workdir", str(tmp_path / "work"), "--out", str(out)]) == 0
    import csv
    rows = list(csv.DictReader(open(out / "traces.csv", encoding="utf-8")))
    assert len(rows) == len(SCENARIOS) * 3
    assert {r["scenario"] for r in rows} == {s.name for s in SCENARIOS}
    assert {r["label"] for r in rows} <= set(metrics.LABELS)
    for f in ("confusion.csv", "metrics.csv", "latency.csv", "receipt_timing.csv", "storage.csv", "summary.md"):
        assert (out / f).stat().st_size > 0, f
    assert (tmp_path / "work" / harness.MARKER).exists()


def test_scenario_labels_match_the_brief():
    labels = {s.name: s.label for s in SCENARIOS}
    assert labels["clean_authorized_run"] == "legitimate"
    assert {labels[n] for n in ("naive_artifact_tamper", "log_rewriting", "forward_recompute", "key_forgery",
                                "replayed_receipt")} == {"tampered"}
    assert {labels[n] for n in ("signed_but_unauthorized", "plan_deviation", "window_over_24h")} == {"policy_violation"}
    assert {labels[n] for n in ("omitted_evidence", "unreconcilable_counts", "truncated_trace")} == {"insufficient"}


def test_examples_are_synthetic_and_contain_no_local_paths():
    ex = REPO / "examples"
    expected = {"verified": "VERIFIED WITHIN SCOPE", "failed": "VERIFICATION FAILED",
                "false-assurance": "VERIFIED WITHIN SCOPE", "insufficient": "INSUFFICIENT EVIDENCE"}
    import json
    for name, status in expected.items():
        v = json.loads((ex / name / "verdict.json").read_text(encoding="utf-8"))
        assert v["status"] == status and (ex / name / "badge.svg").is_file()
        assert v["env"]["vault"] == "test" and v["env"]["db"] == "test"
    for f in ex.rglob("*"):
        if f.is_file():
            text = f.read_text(encoding="utf-8", errors="replace")
            assert "\\Users\\" not in text and "/home/" not in text and "AppData" not in text, f


def test_workdir_guards(tmp_path):
    for bad in (REPO, REPO / "vault", REPO / "keys", REPO / "vault-test" / "x", REPO.parent):
        with pytest.raises(SystemExit):
            harness.prepare_workdir(bad)
    unmarked = tmp_path / "data"
    unmarked.mkdir()
    (unmarked / "keep.txt").write_text("x")
    with pytest.raises(SystemExit, match="marker"):
        harness.prepare_workdir(unmarked)
    assert (unmarked / "keep.txt").exists()


def test_metrics_against_hand_computed_example():
    r = lambda label, verdict, cfg="A", truth=None, first=None, sc="s": {
        "scenario": sc, "label": label, "config": cfg, "verdict": verdict, "truth_step": truth, "first_step": first}
    rows = [r("legitimate", V), r("legitimate", I),                       # 1 false alarm of 2
            r("tampered", F, truth=2, first=2), r("tampered", F, truth=2, first=3), r("tampered", V, truth=0),
            r("policy_violation", V, truth=1), r("policy_violation", F, truth=1, first=1),
            r("insufficient", V), r("insufficient", I), r("insufficient", F)]
    m = metrics.compute(rows)["per_config"]["A"]
    # non-legitimate: 8 traces, verified: tampered 1 + policy 1 + insufficient 1 = 3
    assert (m["false_assurance"]["numerator"], m["false_assurance"]["denominator"]) == (3, 8)
    assert m["false_assurance[policy_violation]"]["value"] == 0.5
    # positives = tampered + policy (5). TP = 3 (F among them), FN = 2, FP = 1 (insufficient got F)
    assert m["precision"]["value"] == pytest.approx(3 / 4) and m["recall"]["value"] == pytest.approx(3 / 5)
    assert m["f1"]["value"] == pytest.approx(2 * (3 / 4) * (3 / 5) / (3 / 4 + 3 / 5))
    assert (m["false_alarm"]["numerator"], m["false_alarm"]["denominator"]) == (1, 2)
    assert m["insufficient_recognition"]["value"] == pytest.approx(1 / 3)
    # F with a truth step: 3 traces; first step correct in 2
    assert (m["localization_accuracy"]["numerator"], m["localization_accuracy"]["denominator"]) == (2, 3)
    assert metrics.compute(rows)["confusion"]["A"]["tampered"] == {"V": 1, "F": 2, "I": 0, "total": 3}
    assert metrics.rate(0, 0)["value"] is None
    assert metrics.p95([float(i) for i in range(1, 21)]) == 19.0 and metrics.p95([]) is None
