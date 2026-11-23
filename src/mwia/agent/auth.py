"""iNaturalist token handling. The token is never printed, logged, hashed into a receipt or returned.

The JWT `exp` claim is decoded without checking the signature (it's used only for scheduling). If the
token is missing, malformed, expired, or expires within `min_token_validity_minutes`, the agent falls back to
anonymous reads when policy auth.allow_anonymous is true, and raises a "token needs refresh" warning.
The v2 OpenAPI spec lists GET /observations with optional user JWT auth in the `Authorization` header (raw
token, apiKey scheme). Receipts record only auth_mode, the token's expiry time and the reason.
AI-assisted (Claude). Verified by: tests/test_agent_units.py (auth cases).
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone


class AuthError(Exception):
    pass


def _exp(token: str) -> datetime | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        return datetime.fromtimestamp(int(exp), tz=timezone.utc)
    except Exception:
        return None


def resolve(token: str | None, now: datetime, min_valid_minutes: int, allow_anonymous: bool) -> dict:
    """Returns {auth_mode, token_exp, reason, warning}. The token itself is never part of the result."""
    exp_s = None
    if token:
        exp = _exp(token)
        exp_s = exp.strftime("%Y-%m-%dT%H:%M:%SZ") if exp else None
        if exp is None:
            reason = "token_malformed"
        elif exp <= now:
            reason = "token_expired"
        elif exp - now < timedelta(minutes=min_valid_minutes):
            reason = "token_expires_soon"
        else:
            return {"auth_mode": "token", "token_exp": exp_s, "reason": "token_valid", "warning": None}
    else:
        reason = "token_missing"
    if not allow_anonymous:
        raise AuthError(f"no usable iNaturalist token ({reason}) and policy forbids anonymous access")
    warning = None if reason == "token_missing" else (
        "iNaturalist token needs refresh: paste a new one from https://www.inaturalist.org/users/api_token into .env")
    return {"auth_mode": "anonymous", "token_exp": exp_s, "reason": reason, "warning": warning}
