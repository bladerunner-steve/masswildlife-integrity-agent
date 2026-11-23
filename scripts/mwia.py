"""Command-line entry point that works without installing the package:

  .venv\\Scripts\\python.exe scripts\\mwia.py agent run [--dry-run] [--vault prod|test] [--db prod|test] [--window-hours N]
  .venv\\Scripts\\python.exe scripts\\mwia.py notary keygen|rotate|pubkey
  .venv\\Scripts\\python.exe scripts\\mwia.py verify [--vault prod|test] [--run ID | --all] [--mode crypto|crypto+policy|crypto+policy+evidence] [--json]

It puts src/ on sys.path and dispatches.
AI-assisted (Claude). Verified by: tests/test_pipeline.py (CLI usage errors) and the Checkpoint 3 runs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1:3] == ["agent", "run"]:
        from mwia.agent.pipeline import main as run
        return run(sys.argv[3:])
    if len(sys.argv) >= 2 and sys.argv[1] == "notary":
        from mwia.notary.__main__ import main as notary
        return notary(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] == "verify":
        from mwia.verify.__main__ import main as verify
        return verify(sys.argv[2:])
    print(__doc__.strip(), file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
