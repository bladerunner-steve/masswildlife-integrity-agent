"""Pre-commit secret check: fails if a staged file looks like a secret or private data.

Blocks (by path): .env and .env.* (except .env.example), *.pem / *.key outside keys/public/, anything under
keys/private/, vault*/, anchors*/, data/, logs/, reports/runs/.
Blocks (by content): JSON Web Tokens (eyJ...xxx.yyy.zzz), PEM private keys of any kind, and the actual values of
INAT_API_TOKEN, MYSQL_PASSWORD and NOTARY_KEY_PASSPHRASE from the local .env (if they are long enough to match
safely). Values are compared in memory and never printed.
Usage:  python scripts/precommit_check.py            (checks the staged files; used by .githooks/pre-commit)
        python scripts/precommit_check.py --all      (checks every file `git add -A` would add)
Enable the hook once with:  git config core.hooksPath .githooks
AI-assisted (Claude). Verified by: tests/test_precommit.py.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
SECRET_VARS = ("INAT_API_TOKEN", "MYSQL_PASSWORD", "NOTARY_KEY_PASSPHRASE")
BLOCKED_PATHS = [".env", ".env.*", "**/.env", "keys/private/*", "keys/private/**", "vault/*", "vault-*/*", "anchors/*",
                 "anchors-*/*", "data/*", "logs/*", "reports/runs/*"]


def path_problem(path: str) -> str | None:
    p = path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    if name == ".env.example":
        return None
    for pat in BLOCKED_PATHS:
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, pat.rstrip("*") + "**"):
            return f"path is never committed ({pat})"
    if (name.endswith(".pem") or name.endswith(".key")) and not p.startswith("keys/public/"):
        return "key/PEM file outside keys/public/"
    return None


def content_problems(data: bytes, secrets: list[bytes]) -> list[str]:
    out = []
    if JWT.search(data):
        out.append("looks like a JSON Web Token (JWT)")
    if PRIVATE_KEY.search(data):
        out.append("contains a PEM private key")
    if any(s in data for s in secrets):
        out.append("contains a secret value from .env")
    return out


def local_secrets(env_file: Path) -> list[bytes]:
    if not env_file.is_file():
        return []
    from dotenv import dotenv_values
    vals = dotenv_values(env_file)
    return [v.encode() for k in SECRET_VARS if (v := vals.get(k)) and len(v) >= 8 and v.lower() != "change_me"]


def check(files: list[tuple[str, bytes]], secrets: list[bytes]) -> list[tuple[str, str]]:
    problems = []
    for path, data in files:
        if (pp := path_problem(path)):
            problems.append((path, pp))
        for cp in content_problems(data, secrets):
            problems.append((path, cp))
    return problems


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def staged_files() -> list[tuple[str, bytes]]:
    names = [n for n in _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0") if n]
    return [(n, _git("show", f":{n}")) for n in names]


def would_add_files() -> list[tuple[str, bytes]]:
    out = _git("add", "-A", "--dry-run").decode()
    names = [l[len("add '"):-1] for l in out.splitlines() if l.startswith("add '")]
    return [(n, (ROOT / n).read_bytes()) for n in names if (ROOT / n).is_file()]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    files = would_add_files() if "--all" in argv else staged_files()
    problems = check(files, local_secrets(ROOT / ".env"))
    if problems:
        print("pre-commit secret check FAILED:", file=sys.stderr)
        for path, why in problems:
            print(f"  {path}: {why}", file=sys.stderr)
        print("Unstage these files (git restore --staged <file>) or remove the secret.", file=sys.stderr)
        return 1
    print(f"pre-commit secret check passed ({len(files)} file(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
