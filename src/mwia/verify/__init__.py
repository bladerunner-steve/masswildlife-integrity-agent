"""Independent, read-only verifier: 3 layers (A crypto, B policy, C evidence), the integrity badge and reports.

Inputs only: the vault (read through a read-only reader), the trusted public keys (keys/public), the anchors
file and config/verifier.yaml (pins). It never imports mwia.agent or mwia.index and never reads MySQL. It
re-evaluates policy from the signed PR0 snapshot with its own code (not the agent's gate). Outputs:
verdict.json, badge.svg and index.html per run, plus reports/index.html.
AI-assisted (Claude). Verified by: tests/test_verify.py (including an import-independence test).
"""
