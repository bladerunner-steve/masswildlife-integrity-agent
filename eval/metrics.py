"""Evaluation metrics, computed only from measured verdicts and the scenarios' ground-truth labels.

Definitions (per verifier configuration A, B, C):
  false-assurance rate     traces labelled non-legitimate that got VERIFIED WITHIN SCOPE / all non-legitimate
                           traces (also broken down per label and per scenario)
  violation detection      positive = label tampered or policy_violation; predicted positive = VERIFICATION
                           FAILED. Precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = harmonic mean
  false alarms             legitimate traces not VERIFIED (split into FAILED and INSUFFICIENT) / legitimate traces
  insufficient recognition insufficient-labelled traces with INSUFFICIENT EVIDENCE / insufficient-labelled traces
  localization accuracy    traces with a known truth step that got FAILED and whose first failing step equals the
                           truth step / traces with a known truth step that got FAILED
Rates carry their numerator and denominator. A rate with denominator 0 is reported as empty, not 0.
p95 uses the nearest-rank method.
AI-assisted (Claude). Verified by: tests/test_eval.py (hand-computed metric example).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

V, F, I = "VERIFIED WITHIN SCOPE", "VERIFICATION FAILED", "INSUFFICIENT EVIDENCE"
SHORT = {V: "V", F: "F", I: "I"}
LABELS = ["legitimate", "tampered", "policy_violation", "insufficient"]
CONFIGS = ["A", "B", "C"]


def rate(num: int, den: int) -> dict:
    return {"value": (num / den) if den else None, "numerator": num, "denominator": den}


def p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def compute(rows: list[dict]) -> dict:
    """rows: one per (trace, config): scenario, label, config, verdict, first_step, truth_step."""
    out = {"per_config": {}, "confusion": {}, "per_scenario": defaultdict(dict)}
    for cfg in CONFIGS:
        rs = [r for r in rows if r["config"] == cfg]
        neg = [r for r in rs if r["label"] != "legitimate"]
        m = {"false_assurance": rate(sum(r["verdict"] == V for r in neg), len(neg))}
        for lab in LABELS[1:]:
            lr = [r for r in rs if r["label"] == lab]
            m[f"false_assurance[{lab}]"] = rate(sum(r["verdict"] == V for r in lr), len(lr))
        pos = lambda r: r["label"] in ("tampered", "policy_violation")
        tp = sum(pos(r) and r["verdict"] == F for r in rs)
        fp = sum(not pos(r) and r["verdict"] == F for r in rs)
        fn = sum(pos(r) and r["verdict"] != F for r in rs)
        m["precision"] = rate(tp, tp + fp)
        m["recall"] = rate(tp, tp + fn)
        p, rc = m["precision"]["value"], m["recall"]["value"]
        m["f1"] = {"value": (2 * p * rc / (p + rc)) if p is not None and rc is not None and (p + rc) else None,
                   "numerator": None, "denominator": None}
        legit = [r for r in rs if r["label"] == "legitimate"]
        m["false_alarm"] = rate(sum(r["verdict"] != V for r in legit), len(legit))
        m["false_alarm[FAILED]"] = rate(sum(r["verdict"] == F for r in legit), len(legit))
        m["false_alarm[INSUFFICIENT]"] = rate(sum(r["verdict"] == I for r in legit), len(legit))
        ins = [r for r in rs if r["label"] == "insufficient"]
        m["insufficient_recognition"] = rate(sum(r["verdict"] == I for r in ins), len(ins))
        loc = [r for r in rs if r["truth_step"] is not None and r["verdict"] == F]
        m["localization_accuracy"] = rate(sum(r["first_step"] == r["truth_step"] for r in loc), len(loc))
        out["per_config"][cfg] = m
        cm = {lab: Counter(SHORT[r["verdict"]] for r in rs if r["label"] == lab) for lab in LABELS}
        out["confusion"][cfg] = {lab: {"V": c["V"], "F": c["F"], "I": c["I"], "total": sum(c.values())}
                                 for lab, c in cm.items()}
        for sc in sorted({r["scenario"] for r in rs}):
            sr = [r for r in rs if r["scenario"] == sc]
            c = Counter(SHORT[r["verdict"]] for r in sr)
            out["per_scenario"][sc][cfg] = {"V": c["V"], "F": c["F"], "I": c["I"], "total": len(sr),
                                            "label": sr[0]["label"]}
    return out
