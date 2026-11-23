"""Unit tests for agent building blocks: auth (token expiry), policy gate, HTTP client, transform, window.
AI-assisted (Claude)."""
import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from mwia.agent import auth, policy_gate
from mwia.agent.http import HttpError, InatClient
from mwia.agent.m1_request import build_params
from mwia.agent.pipeline import compute_window
from mwia.agent.transform import COLUMNS, FIELDS, time_zone, to_row

REPO = Path(__file__).resolve().parents[1]
POLICY = yaml.safe_load((REPO / "config" / "policy.yaml").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
WINDOW = {"start": "2026-11-22T12:00:00Z", "end": "2026-11-23T12:00:00Z"}
URL = "https://api.inaturalist.org/v2/observations"


def jwt(exp: datetime) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'HS512'})}.{enc({'user_id': 1, 'exp': int(exp.timestamp())})}.c2ln"


# ---------------- auth ----------------

def test_valid_token():
    tok = jwt(NOW + timedelta(hours=20))
    r = auth.resolve(tok, NOW, 60, True)
    assert r == {"auth_mode": "token", "token_exp": "2026-11-24T08:00:00Z", "reason": "token_valid", "warning": None}
    assert tok not in json.dumps(r)


@pytest.mark.parametrize("tok,reason", [(None, "token_missing"), ("garbage", "token_malformed"),
                                        (jwt(NOW - timedelta(minutes=1)), "token_expired"),
                                        (jwt(NOW + timedelta(minutes=59)), "token_expires_soon")])
def test_fallback_to_anonymous(tok, reason):
    r = auth.resolve(tok, NOW, 60, True)
    assert r["auth_mode"] == "anonymous" and r["reason"] == reason
    assert (r["warning"] is None) == (reason == "token_missing")
    if tok:
        assert tok not in json.dumps(r)


def test_anonymous_forbidden():
    with pytest.raises(auth.AuthError):
        auth.resolve(None, NOW, 60, False)


# ---------------- policy gate ----------------

def good():
    return build_params(POLICY, WINDOW)


def test_gate_passes_the_agents_own_request():
    assert policy_gate.evaluate("GET", URL, good(), POLICY, WINDOW) == ("pass", policy_gate.RULES, [])
    assert policy_gate.evaluate("GET", URL, dict(good(), id_above=5), POLICY, WINDOW)[0] == "pass"


@pytest.mark.parametrize("method,url,change,rule", [
    ("POST", URL, {}, "src.method"),
    ("GET", URL.replace("https", "http"), {}, "src.scheme"),
    ("GET", URL.replace("api.inaturalist.org", "evil.example"), {}, "src.host"),
    ("GET", URL.replace("/v2/observations", "/v1/observations"), {}, "src.endpoint"),
    ("GET", URL, {"project_id": 12345}, "src.project"),
    ("GET", URL, {"place_id": 1}, "src.forbidden_param"),
    ("GET", URL, {"lat": 42.0}, "src.forbidden_param"),
    ("GET", URL, {"user_id": 3}, "src.forbidden_param"),
    ("GET", URL, {"taxon_id": 3}, "src.allowed_params"),
    ("GET", URL, {"order": "desc"}, "src.required_params"),
    ("GET", URL, {"fields": FIELDS[:-1] + ",private_geojson:!t)"}, "src.forbidden_fields"),
    ("GET", URL, {"created_d1": "2026-11-22T11:00:00Z"}, "win.params"),
    ("GET", URL, {"per_page": 500}, "rate.per_page"),
])
def test_gate_violations(method, url, change, rule):
    decision, _, violations = policy_gate.evaluate(method, url, dict(good(), **change), POLICY, WINDOW)
    assert decision == "violation" and rule in violations


def test_gate_window_too_long_and_reversed():
    long_w = {"start": "2026-11-22T11:40:00Z", "end": "2026-11-23T12:00:00Z"}   # 24 h 20 min > 24 h 15 min
    assert "win.max_length" in policy_gate.evaluate("GET", URL, build_params(POLICY, long_w), POLICY, long_w)[2]
    ok_w = {"start": "2026-11-22T11:45:00Z", "end": "2026-11-23T12:00:00Z"}     # exactly 24 h + grace
    assert policy_gate.evaluate("GET", URL, build_params(POLICY, ok_w), POLICY, ok_w)[0] == "pass"
    rev = {"start": WINDOW["end"], "end": WINDOW["start"]}
    assert "win.order" in policy_gate.evaluate("GET", URL, build_params(POLICY, rev), POLICY, rev)[2]


def test_removing_project_is_a_violation():
    p = build_params(POLICY, WINDOW, {"project_id": None})
    assert "src.project" in policy_gate.evaluate("GET", URL, p, POLICY, WINDOW)[2]


# ---------------- HTTP client ----------------

class Resp:
    def __init__(self, status, body=b"{}", headers=None):
        self.status_code, self.content, self.headers, self.url = status, body, headers or {}, URL


class Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params, headers, timeout):
        self.calls.append(headers)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(round(s, 3))
        self.t += s


def client(responses, token=None, attempts=5):
    c = Clock()
    s = Session(responses)
    return InatClient("masswildlife-integrity-agent/0.1", 60, token=token, max_attempts=attempts, session=s,
                      sleep=c.sleep, clock=c), s, c


def test_rate_limit_spacing_and_headers():
    cl, s, c = client([Resp(200), Resp(200), Resp(200)])
    for _ in range(3):
        cl.get(URL, {})
    assert c.sleeps == [1.0, 1.0]
    assert all(h["User-Agent"] == "masswildlife-integrity-agent/0.1" and "Authorization" not in h for h in s.calls)


def test_token_only_in_header_never_in_record():
    cl, s, _ = client([Resp(200)], token="secret.jwt.token")
    _, rec = cl.get(URL, {})
    assert s.calls[0]["Authorization"] == "secret.jwt.token"
    assert "secret" not in json.dumps(rec) and "Authorization" not in cl.public_headers()


def test_retries_429_with_retry_after_then_5xx_then_ok():
    import requests
    cl, _, c = client([Resp(429, headers={"Retry-After": "7"}), Resp(503), requests.ConnectionError(), Resp(200)])
    body, rec = cl.get(URL, {})
    assert [a.get("status", a.get("error")) for a in rec["attempts"]] == [429, 503, "ConnectionError", 200]
    assert 7.0 in c.sleeps and 2.0 in c.sleeps and 4.0 in c.sleeps


def test_gives_up_and_does_not_retry_4xx():
    cl, _, _ = client([Resp(500)] * 3, attempts=3)
    with pytest.raises(HttpError, match="gave up after 3"):
        cl.get(URL, {})
    cl, s, _ = client([Resp(422), Resp(200)])
    with pytest.raises(HttpError, match="HTTP 422"):
        cl.get(URL, {})
    assert len(s.calls) == 1


# ---------------- transform (golden row from the author's existing table) ----------------

POOL = json.loads((REPO / "tests" / "fixtures" / "observations_pool.json").read_text(encoding="utf-8"))["results"]

# Row 416484107 as stored by the author's CSV import (inspected 2026-11-23), with the observer's id and login
# pseudonymized the same way as the fixture, and private_* as NULL (the agent's rule; existing rows hold '').
GOLDEN_416484107 = {
    "id": 416484107, "uuid": "951a3f77-c2aa-4397-bd85-f3f780b15b3f", "observed_on_string": "2026-11-22 15:09:14",
    "observed_on": "2026-11-22", "time_observed_at": "2026-11-22 20:09:14 UTC",
    "time_zone": "Eastern Time (US & Canada)", "user_id": 1001, "user_login": "observer_1", "user_name": "",
    "created_at": "2026-11-23 04:36:13 UTC", "updated_at": "2026-11-23 10:57:10 UTC", "quality_grade": "research",
    "license": "CC-BY-NC", "url": "https://www.inaturalist.org/observations/416484107",
    "image_url": "https://inaturalist-open-data.s3.amazonaws.com/photos/767029940/medium.jpg", "sound_url": "",
    "tag_list": "", "description": "", "num_identification_agreements": 1, "num_identification_disagreements": 0,
    "captive_cultivated": "false", "oauth_application_id": "843", "place_guess": "Chipman Rd, Chester, MA, US",
    "latitude": 42.38143, "longitude": -73.001655555, "positional_accuracy": "4", "private_place_guess": None,
    "private_latitude": None, "private_longitude": None, "public_positional_accuracy": "4", "geoprivacy": "",
    "taxon_geoprivacy": "open", "coordinates_obscured": "false", "positioning_method": "", "positioning_device": "",
    "species_guess": "Black-capped Chickadee", "scientific_name": "Poecile atricapillus",
    "common_name": "Black-capped Chickadee", "iconic_taxon_name": "Aves", "taxon_id": 144815,
}


def test_golden_row_matches_existing_table():
    obs = next(o for o in POOL if o["id"] == 416484107)
    assert to_row(obs) == GOLDEN_416484107


def test_all_fixture_rows_are_well_formed_and_geoprivate():
    for o in POOL:
        r = to_row(o)
        assert list(r) == COLUMNS
        assert r["private_latitude"] is None and r["private_longitude"] is None and r["private_place_guess"] is None
        assert r["created_at"].endswith(" UTC") and len(r["created_at"]) == 23
        assert "private_geojson" not in o and "private_location" not in o


def test_unknown_time_zone_kept_raw():
    assert time_zone("America/New_York") == ("Eastern Time (US & Canada)", True)
    assert time_zone("Asia/Tokyo") == ("Asia/Tokyo", False)
    assert time_zone(None) == ("", True)


def test_fields_never_request_private_coordinates():
    assert all(f not in FIELDS for f in POLICY["source"]["forbidden_fields"])
    assert "place_ids:!t" in FIELDS


# ---------------- window ----------------

def test_window_first_run_and_override():
    w = compute_window(NOW, POLICY, 10, None, None)
    assert (w["start"], w["end"], w["source"], w["gap_seconds"]) == ("2026-11-22T12:00:00Z", "2026-11-23T12:00:00Z",
                                                                    "first_run", None)
    assert compute_window(NOW, POLICY, 10, None, 2)["start"] == "2026-11-23T10:00:00Z"


def test_window_incremental_with_overlap():
    last = datetime(2026, 11, 22, 12, 5)  # naive UTC, as stored in MySQL
    w = compute_window(NOW, POLICY, 10, last, None)
    assert w["start"] == "2026-11-22T11:55:00Z" and w["gap_seconds"] is None


def test_window_cap_and_gap_flag():
    last = datetime(2026, 11, 22, 6, 0)   # 30 h before NOW: the scheduler missed ~6 h
    w = compute_window(NOW, POLICY, 10, last, None)
    assert w["start"] == "2026-11-22T11:45:00Z"           # capped at 24 h + 15 min, never widened
    assert w["gap_seconds"] == int(timedelta(hours=5, minutes=45).total_seconds())
