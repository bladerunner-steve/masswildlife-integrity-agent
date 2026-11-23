"""Rate-limited, retrying HTTP GET client for the iNaturalist API.

Requests are spaced at least 60 / max_requests_per_minute seconds apart (1 s under the current policy).
HTTP 429 and 5xx responses, and connection errors, are retried with exponential backoff (1, 2, 4, ... s,
capped at 60 s), and a Retry-After header is honoured. The User-Agent is masswildlife-integrity-agent/0.1.
The token, if any, goes only into the Authorization header of the outgoing request. It is never stored in
the returned record.
AI-assisted (Claude). Verified by: tests/test_agent_units.py (spacing, retries, give-up) with a fake session.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpError(Exception):
    def __init__(self, message: str, record: dict):
        super().__init__(message)
        self.record = record


class InatClient:
    def __init__(self, user_agent: str, max_requests_per_minute: int, token: str | None = None,
                 timeout: float = 60.0, max_attempts: int = 5, session=None, sleep=time.sleep, clock=time.monotonic,
                 wall=lambda: datetime.now(timezone.utc)):
        self.user_agent = user_agent
        self.min_interval = 60.0 / max_requests_per_minute
        self._token = token
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.session = session or requests.Session()
        self.sleep, self.clock, self.wall = sleep, clock, wall
        self._last: float | None = None
        self.request_count = 0

    def public_headers(self) -> dict:
        return {"User-Agent": self.user_agent, "Accept": "application/json"}

    def _wait_turn(self) -> None:
        if self._last is not None:
            delay = self._last + self.min_interval - self.clock()
            if delay > 0:
                self.sleep(delay)
        self._last = self.clock()

    def get(self, url: str, params: dict) -> tuple[bytes, dict]:
        """GET with retries. Returns (body, record); the record holds no auth material."""
        headers = self.public_headers()
        if self._token:
            headers["Authorization"] = self._token
        attempts = []
        for attempt in range(1, self.max_attempts + 1):
            self._wait_turn()
            started = self.clock()
            fetched_at = self.wall().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            self.request_count += 1
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                attempts.append({"attempt": attempt, "error": type(e).__name__})
                status, retry_after, body, final_url = None, None, b"", None
            else:
                status, body, final_url = r.status_code, r.content, r.url
                retry_after = r.headers.get("Retry-After")
                attempts.append({"attempt": attempt, "status": status})
            elapsed_ms = round((self.clock() - started) * 1000, 1)
            record = {"url": final_url, "status": status, "fetched_at": fetched_at, "elapsed_ms": elapsed_ms,
                      "attempts": attempts}
            if status == 200:
                return body, record
            if status is not None and status not in RETRY_STATUSES:
                raise HttpError(f"HTTP {status}", record)
            if attempt == self.max_attempts:
                raise HttpError(f"gave up after {attempt} attempts", record)
            backoff = min(60.0, 2.0 ** (attempt - 1))
            try:
                backoff = max(backoff, float(retry_after)) if retry_after else backoff
            except ValueError:
                pass
            self.sleep(min(backoff, 120.0))
        raise AssertionError("unreachable")
