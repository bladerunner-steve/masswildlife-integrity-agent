"""The scheduled ingest agent: six modules (M0 plan ... M5 complete), each emitting exactly one receipt.

Entry point: `python scripts/mwia.py agent run ...` (or `python -m mwia.agent run ...` with src on the path).
AI-assisted (Claude). Verified by: tests/test_pipeline.py and the module-level tests listed in each file.
"""
