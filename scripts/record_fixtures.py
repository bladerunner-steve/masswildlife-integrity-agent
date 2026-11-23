"""Dev tool: record real iNaturalist v2 responses as offline test fixtures (tests/fixtures/).

It fetches one short, fixed past window for project 46777 with the agent's exact `fields` (no private
fields are requested). It then redacts observer identity (user.id -> 1000+n, user.login -> observer_<n>,
user.name -> '', description -> '') because this repo is public, and writes:
  tests/fixtures/observations_pool.json    the redacted observations, sorted by id
  tests/fixtures/README.md                 what was recorded, when, and how it was redacted
Anonymous, <= 1 request/s, User-Agent masswildlife-integrity-agent/0.1.
AI-assisted (Claude). Verified by: tests/test_agent_units.py (fixture sanity) and tests/test_pipeline.py.
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mwia.agent.transform import FIELDS  # noqa: E402

WINDOW = ("2026-11-23T03:30:00Z", "2026-11-23T04:40:00Z")


def main() -> int:
    s = requests.Session()
    s.headers.update({"User-Agent": "masswildlife-integrity-agent/0.1", "Accept": "application/json"})
    params = {"project_id": 46777, "created_d1": WINDOW[0], "created_d2": WINDOW[1], "order_by": "id", "order": "asc",
              "per_page": 200, "fields": FIELDS}
    obs, id_above = [], None
    while True:
        p = dict(params, **({"id_above": id_above} if id_above else {}))
        r = s.get("https://api.inaturalist.org/v2/observations", params=p, timeout=60)
        r.raise_for_status()
        res = r.json()["results"]
        obs += res
        if len(res) < 200:
            break
        id_above = res[-1]["id"]
        time.sleep(1.1)
    for key in ("private_geojson", "private_location", "private_place_guess"):
        assert all(key not in o for o in obs), key
    logins: dict[str, str] = {}
    user_ids: dict[int, int] = {}
    for o in obs:
        u = o.get("user") or {}
        if "id" in u:
            u["id"] = user_ids.setdefault(u["id"], 1000 + len(user_ids) + 1)
        if "login" in u:
            u["login"] = logins.setdefault(u["login"], f"observer_{len(logins) + 1}")
        if "name" in u:
            u["name"] = ""
        if o.get("description"):
            o["description"] = ""
    obs.sort(key=lambda o: o["id"])
    fx = ROOT / "tests" / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    (fx / "observations_pool.json").write_text(json.dumps({"window": WINDOW, "results": obs}, indent=1) + "\n",
                                               encoding="utf-8")
    (fx / "README.md").write_text(
        "# Test fixtures\n\n"
        f"`observations_pool.json`: {len(obs)} real observations from `GET /v2/observations` (project 46777, "
        f"created {WINDOW[0]} to {WINDOW[1]}), recorded {time.strftime('%Y-%m-%d', time.gmtime())} by "
        "`scripts/record_fixtures.py` with the agent's own `fields` list.\n\n"
        "Redacted for the public repo: `user.id` -> `1000+<n>`, `user.login` -> `observer_<n>`, `user.name` -> `\"\"`, "
        "`description` -> `\"\"`. "
        "No private/true coordinates are requested or present (only public `geojson`).\n", encoding="utf-8")
    print(f"recorded {len(obs)} observations from {len(logins)} observers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
