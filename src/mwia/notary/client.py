"""Notary client used by the agent. It spawns `python -m mwia.notary serve` as a separate process and talks to
it over stdin/stdout (JSON lines). The agent sends bodies and gets back signed receipts and seals. It never
loads, decrypts or even imports the key code: this module imports only the standard library.
The notary child gets its passphrase from its own environment or reads it from .env itself.
AI-assisted (Claude). Verified by: tests/test_notary_process.py (end-to-end over a real subprocess, and an
import-boundary check that this module pulls in no key-handling code).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2]


class NotaryError(Exception):
    """The notary process failed or refused a request."""


class NotaryClient:
    def __init__(self, keys_dir: Path, env_file: Path | None = None, extra_env: dict[str, str] | None = None,
                 timeout: float = 30.0):
        self.keys_dir = Path(keys_dir)
        self.env_file = env_file
        self.extra_env = extra_env or {}
        self.timeout = timeout
        self._p: subprocess.Popen | None = None
        self.key_id: str | None = None

    def start(self) -> "NotaryClient":
        env = dict(os.environ)
        env.update(self.extra_env)
        env["PYTHONPATH"] = os.pathsep.join([str(SRC_DIR)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        cmd = [sys.executable, "-m", "mwia.notary", "serve", "--keys-dir", str(self.keys_dir)]
        if self.env_file:
            cmd += ["--env-file", str(self.env_file)]
        self._p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", env=env)
        self.key_id = self._call({"op": "hello"})["key_id"]
        return self

    def _call(self, req: dict) -> dict:
        if self._p is None or self._p.poll() is not None:
            raise NotaryError(self._dead_message())
        try:
            self._p.stdin.write(json.dumps(req) + "\n")
            self._p.stdin.flush()
            line = self._p.stdout.readline()
        except (BrokenPipeError, OSError):
            raise NotaryError(self._dead_message()) from None
        if not line:
            raise NotaryError(self._dead_message())
        resp = json.loads(line)
        if not resp.get("ok"):
            raise NotaryError(resp.get("error", "notary refused"))
        return resp

    def _dead_message(self) -> str:
        err = ""
        if self._p is not None:
            try:
                self._p.wait(timeout=5)
                tail = (self._p.stderr.read() or "").strip().splitlines()
                err = tail[-1] if tail else ""
            except Exception:
                pass
        return f"notary process is not running{': ' + err if err else ''}"

    def sign_receipt(self, body: dict) -> dict:
        return self._call({"op": "sign_receipt", "body": body})["receipt"]

    def seal_run(self, run_id: str) -> dict:
        return self._call({"op": "seal_run", "run_id": run_id})["seal"]

    def close(self) -> None:
        if self._p is None:
            return
        try:
            if self._p.poll() is None:
                self._p.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                self._p.stdin.flush()
                self._p.wait(timeout=self.timeout)
        except Exception:
            self._p.kill()
        finally:
            for s in (self._p.stdin, self._p.stdout, self._p.stderr):
                try:
                    s.close()
                except Exception:
                    pass
            self._p = None

    def __enter__(self) -> "NotaryClient":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()
