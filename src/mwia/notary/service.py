"""Notary signing service: validates and signs receipt bodies, then seals each run with a Merkle root.

Rules the notary enforces (it is a witness, not a policy engine; policy is the verifier's job):
- the body passes the strict receipt/v1 schema, and its notary_key_id is the notary's active key;
- a run's first receipt is PR0, and each later receipt's prev_hash equals the hash the notary last signed
  for that run (no forks, no gaps in the chain);
- the seal is built from the notary's own record of the hashes it signed, so a receipt can't be left out.
  Sealing requires the last receipt to be PR5, and a sealed run accepts nothing more.
The notary does not check step order or plan conformance. Validly signed plan deviations must stay possible,
because they are exactly the case the policy layer (B) is evaluated on.
stdio protocol: one JSON object per line. Request {"op": ...}; response {"ok": true, ...} or
{"ok": false, "error": "..."}. Ops: hello, sign_receipt {body}, seal_run {run_id}, shutdown.
AI-assisted (Claude). Verified by: tests/test_chain.py (in-process) and tests/test_notary_process.py
(subprocess).
"""
from __future__ import annotations

import json
from typing import IO

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from mwia.common import merkle
from mwia.common.canonical import hash_obj, jcs
from mwia.common.receipt import new_nonce, validate_receipt_body, validate_seal_body
from mwia.common.timeutil import utc_now


class NotaryRefusal(Exception):
    pass


class Notary:
    def __init__(self, private_key: Ed25519PrivateKey, key_id: str):
        self._key = private_key
        self.key_id = key_id
        self._runs: dict[str, dict] = {}

    def _sign(self, body: dict) -> tuple[str, str]:
        return hash_obj(body), self._key.sign(jcs(body)).hex()

    def sign_receipt(self, body: dict) -> dict:
        try:
            body = validate_receipt_body(body)
        except (ValidationError, ValueError) as e:
            raise NotaryRefusal(f"invalid receipt body: {e}") from None
        if body["notary_key_id"] != self.key_id:
            raise NotaryRefusal("notary_key_id is not this notary's active key")
        run = self._runs.get(body["run_id"])
        if run is None:
            if body["step"] != 0:
                raise NotaryRefusal("the first receipt of a run must be PR0")
            run = self._runs[body["run_id"]] = {"hashes": [], "steps": [], "prev_seal": body["prev_hash"],
                                                "sealed": False}
        else:
            if run["sealed"]:
                raise NotaryRefusal("run is already sealed")
            if body["step"] == 0:
                raise NotaryRefusal("run already has a PR0")
            if body["prev_hash"] != run["hashes"][-1]:
                raise NotaryRefusal("prev_hash does not extend this run's chain")
        h, sig = self._sign(body)
        run["hashes"].append(h)
        run["steps"].append(body["step"])
        return {"body": body, "receipt_hash": h, "signature": sig}

    def seal_run(self, run_id: str) -> dict:
        run = self._runs.get(run_id)
        if run is None:
            raise NotaryRefusal("unknown run")
        if run["sealed"]:
            raise NotaryRefusal("run is already sealed")
        if run["steps"][-1] != 5:
            raise NotaryRefusal("a run is sealed only after its PR5 receipt")
        body = validate_seal_body({
            "schema": "seal/v1", "run_id": run_id, "merkle_root": merkle.root_hex(run["hashes"]),
            "receipt_count": len(run["hashes"]), "head_hash": run["hashes"][-1],
            "prev_seal_hash": run["prev_seal"], "nonce": new_nonce(), "timestamp": utc_now(),
            "notary_key_id": self.key_id,
        })
        h, sig = self._sign(body)
        run["sealed"] = True
        return {"body": body, "seal_hash": h, "signature": sig}

    def handle(self, req: dict) -> dict:
        op = req.get("op")
        if op == "hello":
            return {"ok": True, "key_id": self.key_id}
        if op == "sign_receipt":
            return {"ok": True, "receipt": self.sign_receipt(req.get("body"))}
        if op == "seal_run":
            return {"ok": True, "seal": self.seal_run(req.get("run_id"))}
        raise NotaryRefusal(f"unknown op {op!r}")


def serve_stdio(notary: Notary, stdin: IO[str], stdout: IO[str]) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            if req.get("op") == "shutdown":
                stdout.write(json.dumps({"ok": True}) + "\n")
                stdout.flush()
                return
            resp = notary.handle(req)
        except NotaryRefusal as e:
            resp = {"ok": False, "error": str(e)}
        except Exception as e:  # malformed request; never crash silently mid-run
            resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        stdout.write(json.dumps(resp) + "\n")
        stdout.flush()
