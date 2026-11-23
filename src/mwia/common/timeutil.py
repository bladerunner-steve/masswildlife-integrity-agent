"""RFC 3339 UTC timestamps for receipts (always `YYYY-MM-DDTHH:MM:SS.ffffffZ`).

AI-assisted (Claude). Verified by: tests/test_receipts.py (timestamp format validation).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_utc(s: str) -> datetime:
    if not RFC3339_UTC.match(s):
        raise ValueError(f"not an RFC 3339 UTC timestamp: {s!r}")
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
