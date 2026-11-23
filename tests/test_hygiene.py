"""Repository hygiene: every source module carries its AI-disclosure header (what it does, that it was
AI-assisted, how it was verified), as CLAUDE.md requires. AI-assisted (Claude)."""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCES = sorted([*REPO.glob("src/mwia/**/*.py"), *REPO.glob("eval/*.py"), *REPO.glob("scripts/*.py"),
                  *REPO.glob("scripts/*.ps1"), *REPO.glob("scripts/*.sh"), *REPO.glob("templates/*.j2"),
                  *REPO.glob("sql/admin/*.sql")])


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(REPO).as_posix())
def test_module_has_ai_disclosure_header(path):
    head = path.read_text(encoding="utf-8")[:4000]
    assert "AI-assisted" in head, "missing AI-assisted note"
    if path.suffix in (".py", ".ps1", ".sh") and path.name != "__init__.py" or "src/mwia" in path.as_posix():
        assert "Verified by" in head or "verified" in head.lower(), "missing 'Verified by' note"
