# Archived first full run (2026-11-23)

Kept for the record. This run exposed a verifier bug: with PR3's decision list omitted, layer B reported every written record as 'unaccepted' (8/30 omitted_evidence traces FAILED under B and C, all of the decision_list variant). Fixed in src/mwia/verify/policy.py; regression test tests/test_verify.py::test_omitted_mandatory_evidence_is_insufficient_not_failed. The current results in eval/results/ were produced after the fix with the same seed.

Redaction: 9 variant label(s) in traces.csv contained a real iNaturalist user id and were replaced with user_id=<redacted>. No verdict or metric changed.
