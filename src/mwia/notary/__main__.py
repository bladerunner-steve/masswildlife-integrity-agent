"""Notary CLI: `python -m mwia.notary {keygen|rotate|pubkey|serve}`.

keygen  create the first key (encrypted with NOTARY_KEY_PASSPHRASE)
rotate  create a new active key; keep the old public key so old receipts still verify
pubkey  print the active key id and its public key path
serve   run the stdio signing service (used by mwia.notary.client)
The passphrase comes from the environment, or else from the .env file (only that one variable is read).
It is never printed. Error messages go to stderr; in `serve` mode stdout is reserved for the protocol.
AI-assisted (Claude). Verified by: tests/test_notary_process.py (serve), tests/test_notary_keys.py (keygen/rotate).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

from mwia.common.keyring import PUB_SUFFIX, read_keyring
from mwia.notary.keys import PASSPHRASE_ENV, KeyError_, keygen, load_active_private_key, rotate
from mwia.notary.service import Notary, serve_stdio

ROOT = Path(__file__).resolve().parents[3]


def _passphrase(env_file: Path) -> str | None:
    if os.environ.get(PASSPHRASE_ENV):
        return os.environ[PASSPHRASE_ENV]
    if env_file.is_file():
        return dotenv_values(env_file).get(PASSPHRASE_ENV)
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m mwia.notary")
    ap.add_argument("command", choices=["keygen", "rotate", "pubkey", "serve"])
    ap.add_argument("--keys-dir", type=Path, default=ROOT / "keys")
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    a = ap.parse_args(argv)
    try:
        if a.command == "keygen":
            kid = keygen(a.keys_dir, _passphrase(a.env_file))
            print(f"created notary key {kid}; public key: {a.keys_dir / 'public' / (kid + PUB_SUFFIX)}")
        elif a.command == "rotate":
            old, new = rotate(a.keys_dir, _passphrase(a.env_file))
            print(f"rotated: {old} retired (public key kept), {new} active")
        elif a.command == "pubkey":
            kid = read_keyring(a.keys_dir / "public")["active"]
            print(f"active key {kid}: {a.keys_dir / 'public' / (kid + PUB_SUFFIX)}")
        else:
            key, kid = load_active_private_key(a.keys_dir, _passphrase(a.env_file))
            serve_stdio(Notary(key, kid), sys.stdin, sys.stdout)
    except KeyError_ as e:
        print(f"notary: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"notary: missing file {e.filename} (run `python -m mwia.notary keygen` first?)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
