"""Cross-platform exclusive lock on a persistent lock file (msvcrt.locking on Windows, fcntl.flock on POSIX).

The OS releases the lock when the process exits, so a crashed run never leaves a stale lock behind, and the
lock file is never deleted. Used for the vault write lock and the agent's one-run-at-a-time lock.
AI-assisted (Claude). Verified by: tests/test_vault_local.py (two instances), tests/test_pipeline.py
(overlapping run refused).
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

IS_WINDOWS = os.name == "nt"


class LockTimeout(Exception):
    pass


@contextmanager
def file_lock(path: Path, timeout: float = 30.0, poll: float = 0.05):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    fd = os.open(path, os.O_RDWR)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if IS_WINDOWS:
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"{path.name} is held by another process") from None
                time.sleep(poll)
        try:
            yield
        finally:
            if IS_WINDOWS:
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
