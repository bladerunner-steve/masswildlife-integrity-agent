"""Filesystem permission helpers: owner-only access (notary keys) and write-once hardening (WORM vault).

POSIX: chmod 600/700 (owner-only) and chmod 444 (immutable file).
Windows: icacls. Owner-only = inheritance removed plus a single full-control ACE for the current user
((OI)(CI) on directories, so new files inherit it). Immutable file = read-only attribute plus a deny ACE for
the current user covering delete, write data, append, write attributes and write extended attributes, so the
read-only flag can't simply be cleared. Directories get deny delete / delete-child.
Limit (documented in the README): the owner of a file can always rewrite its ACL, and an administrator can
take ownership, so this is tamper-evidence plus protection against accidents, not tamper-proofing.
AI-assisted (Claude). Verified by: tests/test_notary_keys.py (owner-only), tests/test_vault_local.py (hardening).
"""
from __future__ import annotations

import getpass
import os
import stat
import subprocess
from pathlib import Path

IS_WINDOWS = os.name == "nt"
FILE_DENY = "(DE,WD,AD,WA,WEA)"
DIR_DENY = "(DE,DC)"


def current_principal() -> str:
    user = getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain else user


def _icacls(*args: str) -> None:
    subprocess.run(["icacls", *args], check=True, capture_output=True, text=True)


def owner_only(path: Path) -> None:
    path = Path(path)
    if IS_WINDOWS:
        grant = f"{current_principal()}:(OI)(CI)F" if path.is_dir() else f"{current_principal()}:F"
        _icacls(str(path), "/inheritance:r", "/grant:r", grant)
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def make_immutable(path: Path) -> None:
    """Mark a finished vault file read-only and (on Windows) deny delete/modify to the current user."""
    path = Path(path)
    path.chmod(stat.S_IREAD if IS_WINDOWS else 0o444)
    if IS_WINDOWS:
        _icacls(str(path), "/deny", f"{current_principal()}:{FILE_DENY}")


def protect_append_only(path: Path) -> None:
    """Deny deleting an append-only file such as the ledger (Windows). Appends must stay possible, so write
    access isn't denied; truncation or rewriting is caught by the hash chain and the external anchors."""
    if IS_WINDOWS:
        _icacls(str(path), "/deny", f"{current_principal()}:(DE)")


def protect_dir(path: Path) -> None:
    """Deny deleting a vault directory or removing files from it (Windows). POSIX dirs stay writable so new
    objects can be added; on POSIX, file deletion is governed by the directory, which is a documented limit."""
    if IS_WINDOWS:
        _icacls(str(path), "/deny", f"{current_principal()}:{DIR_DENY}")
