"""`python -m mwia.agent run [flags]`. See mwia.agent.pipeline for the flags and exit codes.

AI-assisted (Claude). Verified by: tests/test_pipeline.py.
"""
import sys

from .pipeline import main

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "run":
        print("usage: python -m mwia.agent run [--dry-run] [--vault prod|test] [--db prod|test] [--window-hours N]",
              file=sys.stderr)
        sys.exit(3)
    sys.exit(main(sys.argv[2:]))
