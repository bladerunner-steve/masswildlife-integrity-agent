"""MySQL access for the agent: a guarded connection (SELECT/INSERT/UPDATE only) and the provenance index.

The provenance index is an untrusted convenience. The verifier never reads it.
AI-assisted (Claude). Verified by: tests/test_index.py.
"""
