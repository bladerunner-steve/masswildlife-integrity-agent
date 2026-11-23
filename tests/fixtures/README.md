# Test fixtures

`observations_pool.json`: 10 real observations from `GET /v2/observations` (project 46777, created 2026-11-23T03:30:00Z to 2026-11-23T04:40:00Z), recorded 2026-11-23 by `scripts/record_fixtures.py` with the agent's own `fields` list.

Redacted for the public repo: `user.id` -> `1000+<n>` (pseudonymized 2026-11-23), `user.login` -> `observer_<n>`, `user.name` -> `""`, `description` -> `""`. No private/true coordinates are requested or present (only public `geojson`).

## Attribution and licence

The observation records come from [iNaturalist](https://www.inaturalist.org), via the project
*MassWildlife's All Wildlife Biodiversity Project* (id 46777). Each record is © its observer and licensed
under Creative Commons Attribution-NonCommercial (CC BY-NC; `license_code: cc-by-nc` on all 10 records; the
licence version is the one shown on each observation's page, see https://creativecommons.org/licenses/by-nc/4.0/).

- **Attribution:** each record's `uri` (for example `https://www.inaturalist.org/observations/416484107`) links to
  the original observation, which credits its observer.
- **Changes made:** the observer's account id, login and display name, and the free-text description, were
  replaced or removed (see above) so the repository holds no personal identifiers. All other fields are as returned by the API.
- **Photos:** the fixtures contain photo URLs only, not the images. Each photo keeps its own licence, shown on
  iNaturalist.
- **Use:** non-commercial, as offline test data for academic research (a university capstone). The rest of
  this repository's licence does not apply to these records.
