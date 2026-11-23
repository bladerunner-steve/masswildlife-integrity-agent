"""iNaturalist v2 observation -> masswildlife.inaturalist row, following docs/FIELD_MAPPING.md (flags A-F
approved by the author on 2026-11-23).

Timestamps -> `YYYY-MM-DD HH:MM:SS UTC`; missing TEXT -> ''; booleans -> 'true'/'false'; private_* -> NULL
(never requested); positioning_method/device -> '' (not in v2). time_zone: IANA -> Rails zone name via a
pinned table, and an unknown zone is stored as the raw IANA name and counted.
AI-assisted (Claude). Verified by: tests/test_agent_units.py (golden row taken from the author's existing
table row for observation 416484107, and fixture rows).
"""
from __future__ import annotations

from datetime import datetime, timezone

COLUMNS = [
    "id", "uuid", "observed_on_string", "observed_on", "time_observed_at", "time_zone", "user_id", "user_login",
    "user_name", "created_at", "updated_at", "quality_grade", "license", "url", "image_url", "sound_url", "tag_list",
    "description", "num_identification_agreements", "num_identification_disagreements", "captive_cultivated",
    "oauth_application_id", "place_guess", "latitude", "longitude", "positional_accuracy", "private_place_guess",
    "private_latitude", "private_longitude", "public_positional_accuracy", "geoprivacy", "taxon_geoprivacy",
    "coordinates_obscured", "positioning_method", "positioning_device", "species_guess", "scientific_name",
    "common_name", "iconic_taxon_name", "taxon_id",
]
PRIVATE = {"private_place_guess", "private_latitude", "private_longitude"}
# Columns compared for "changed" and updated on upsert (id is the key, private_* are never written).
UPDATABLE = [c for c in COLUMNS if c != "id" and c not in PRIVATE]

FIELDS = ("(id:!t,uuid:!t,created_at:!t,updated_at:!t,observed_on:!t,observed_on_string:!t,time_observed_at:!t,"
          "observed_time_zone:!t,quality_grade:!t,license_code:!t,uri:!t,photos:(url:!t),sounds:(file_url:!t),"
          "tags:!t,description:!t,num_identification_agreements:!t,num_identification_disagreements:!t,captive:!t,"
          "oauth_application_id:!t,place_guess:!t,geojson:!t,positional_accuracy:!t,public_positional_accuracy:!t,"
          "geoprivacy:!t,taxon_geoprivacy:!t,obscured:!t,species_guess:!t,"
          "taxon:(id:!t,name:!t,preferred_common_name:!t,iconic_taxon_name:!t),user:(id:!t,login:!t,name:!t),"
          "place_ids:!t,project_ids:!t)")

# IANA -> Rails (ActiveSupport::TimeZone) names for zones expected in Massachusetts data (flag A).
RAILS_TZ = {
    "America/New_York": "Eastern Time (US & Canada)", "America/Chicago": "Central Time (US & Canada)",
    "America/Denver": "Mountain Time (US & Canada)", "America/Phoenix": "Arizona",
    "America/Los_Angeles": "Pacific Time (US & Canada)", "America/Anchorage": "Alaska",
    "Pacific/Honolulu": "Hawaii", "America/Halifax": "Atlantic Time (Canada)", "America/Puerto_Rico": "Puerto Rico",
    "Etc/UTC": "UTC", "UTC": "UTC", "Europe/London": "London",
}


def utc_text(s: str | None) -> str:
    if not s:
        return ""
    return datetime.fromisoformat(s).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def parse_created(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def _s(v) -> str:
    return "" if v is None else str(v)


def _b(v) -> str:
    return "" if v is None else ("true" if v else "false")


def time_zone(iana: str | None) -> tuple[str, bool]:
    """(stored value, known?)"""
    if not iana:
        return "", True
    return (RAILS_TZ[iana], True) if iana in RAILS_TZ else (iana, False)


def to_row(o: dict) -> dict:
    t = o.get("taxon") or {}
    u = o.get("user") or {}
    photos = o.get("photos") or []
    sounds = o.get("sounds") or []
    coords = (o.get("geojson") or {}).get("coordinates") or [None, None]
    tz, _ = time_zone(o.get("observed_time_zone"))
    row = {
        "id": o["id"], "uuid": _s(o.get("uuid")),
        "observed_on_string": _s(o.get("observed_on_string")), "observed_on": _s(o.get("observed_on")),
        "time_observed_at": utc_text(o.get("time_observed_at")), "time_zone": tz,
        "user_id": u.get("id"), "user_login": _s(u.get("login")), "user_name": _s(u.get("name")),
        "created_at": utc_text(o.get("created_at")), "updated_at": utc_text(o.get("updated_at")),
        "quality_grade": _s(o.get("quality_grade")), "license": _s(o.get("license_code")).upper(),
        "url": _s(o.get("uri")),
        "image_url": photos[0]["url"].replace("/square.", "/medium.") if photos and photos[0].get("url") else "",
        "sound_url": _s(sounds[0].get("file_url")) if sounds else "",
        "tag_list": ", ".join(o.get("tags") or []), "description": _s(o.get("description")),
        "num_identification_agreements": o.get("num_identification_agreements"),
        "num_identification_disagreements": o.get("num_identification_disagreements"),
        "captive_cultivated": _b(o.get("captive")), "oauth_application_id": _s(o.get("oauth_application_id")),
        "place_guess": _s(o.get("place_guess")),
        "latitude": float(coords[1]) if coords[1] is not None else None,
        "longitude": float(coords[0]) if coords[0] is not None else None,
        "positional_accuracy": _s(o.get("positional_accuracy")),
        "private_place_guess": None, "private_latitude": None, "private_longitude": None,
        "public_positional_accuracy": _s(o.get("public_positional_accuracy")),
        "geoprivacy": _s(o.get("geoprivacy")), "taxon_geoprivacy": _s(o.get("taxon_geoprivacy")),
        "coordinates_obscured": _b(o.get("obscured")), "positioning_method": "", "positioning_device": "",
        "species_guess": _s(o.get("species_guess")), "scientific_name": _s(t.get("name")),
        "common_name": _s(t.get("preferred_common_name")), "iconic_taxon_name": _s(t.get("iconic_taxon_name")),
        "taxon_id": t.get("id"),
    }
    assert list(row) == COLUMNS
    return row


def differs(new: dict, existing: dict) -> list[str]:
    """Columns (of UPDATABLE) whose values differ."""
    return [c for c in UPDATABLE if new[c] != existing.get(c)]
