# Field mapping: iNaturalist v2 → `masswildlife.inaturalist`

AI-assisted (Claude). Verified 2026-11-23 by: (1) the v2 OpenAPI schema `Observation`, `Photo`, `Sound`,
`User`, `Taxon` at `https://api.inaturalist.org/v2/api-docs`; (2) a live comparison: 48 rows already in the
table were re-fetched from `GET /v2/observations?id=…`, passed through the transforms below, and diffed column
by column. All 35 compared columns matched, except on observation 416482813, which its observer edited after
the export (location, accuracy, species_guess, quality_grade, agreements; the edits are visible in v2
`updated_at`). The Phase 3 transform module gets a unit test that replays this comparison on a recorded fixture.

## Target table (as rebuilt by the author, 2026-11-23)
40 columns, `PRIMARY KEY (id)`, InnoDB utf8mb4. 929 rows at inspection: ids 416380763–416484113,
`created_at` 2026-11-22 19:19:03 → 2026-11-23 04:36:19 UTC. Column names were not changed.

Conventions already in the stored rows, which the agent keeps:
- Timestamps are TEXT in UTC: `YYYY-MM-DD HH:MM:SS UTC`. v2 returns ISO 8601 with the observation's local
  offset (`2026-11-22T23:36:19-05:00`), so the agent converts to UTC. Checked: `…23:36:19-05:00` → `2026-11-23 04:36:19 UTC`.
- Missing values are the empty string `''` in TEXT columns, not NULL. Booleans are the strings `'true'`/`'false'`.
- INT/DOUBLE columns are NULL when v2 returns null.

## Mapping
`fields` request: `(id:!t,uuid:!t,created_at:!t,updated_at:!t,observed_on:!t,observed_on_string:!t,time_observed_at:!t,observed_time_zone:!t,quality_grade:!t,license_code:!t,uri:!t,photos:(url:!t),sounds:(file_url:!t),tags:!t,description:!t,num_identification_agreements:!t,num_identification_disagreements:!t,captive:!t,oauth_application_id:!t,place_guess:!t,geojson:!t,positional_accuracy:!t,public_positional_accuracy:!t,geoprivacy:!t,taxon_geoprivacy:!t,obscured:!t,species_guess:!t,taxon:(id:!t,name:!t,preferred_common_name:!t,iconic_taxon_name:!t),user:(id:!t,login:!t,name:!t),place_ids:!t,project_ids:!t)`

| # | Column | Type | v2 field path | Transform | Verified |
|---|---|---|---|---|---|
| 1 | id | INT NOT NULL, PK | `id` | as is | ✔ 48/48 |
| 2 | uuid | TEXT | `uuid` | as is | ✔ |
| 3 | observed_on_string | TEXT | `observed_on_string` | null → `''` | ✔ |
| 4 | observed_on | TEXT | `observed_on` | `YYYY-MM-DD`; null → `''` | ✔ |
| 5 | time_observed_at | TEXT | `time_observed_at` | ISO → UTC `… UTC`; null → `''` | ✔ |
| 6 | time_zone | TEXT | `observed_time_zone` | IANA → Rails zone name via a pinned lookup (`America/New_York` → `Eastern Time (US & Canada)`). **⚠ Flag A** | ✔ (only zone present) |
| 7 | user_id | INT | `user.id` | as is | ✔ |
| 8 | user_login | TEXT | `user.login` | as is | ✔ |
| 9 | user_name | TEXT | `user.name` | null → `''` | ✔ |
| 10 | created_at | TEXT | `created_at` | ISO → UTC | ✔ (**window field**) |
| 11 | updated_at | TEXT | `updated_at` | ISO → UTC | ✔ 47/48. **⚠ Flag B** |
| 12 | quality_grade | TEXT | `quality_grade` | as is | ✔ |
| 13 | license | TEXT | `license_code` | upper-case (`cc-by-nc` → `CC-BY-NC`); null → `''` | ✔ |
| 14 | url | TEXT | `uri` | as is | ✔ |
| 15 | image_url | TEXT | `photos[0].url` | `/square.` → `/medium.`; no photos → `''` | ✔ |
| 16 | sound_url | TEXT | `sounds[0].file_url` | none → `''` | ✘ not observed (0 sounds in sample). **⚠ Flag C** |
| 17 | tag_list | TEXT | `tags[]` | joined with `", "`; none → `''` | ✘ not observed (0 tags in sample). **⚠ Flag C** |
| 18 | description | TEXT | `description` | null → `''` | ✔ |
| 19 | num_identification_agreements | INT | `num_identification_agreements` | as is | ✔ |
| 20 | num_identification_disagreements | INT | `num_identification_disagreements` | as is | ✔ |
| 21 | captive_cultivated | TEXT | `captive` | bool → `'true'`/`'false'` | ✔ |
| 22 | oauth_application_id | TEXT | `oauth_application_id` | int → string; null → `''` | ✔ |
| 23 | place_guess | TEXT | `place_guess` | null → `''` | ✔ |
| 24 | latitude | DOUBLE | `geojson.coordinates[1]` | public (possibly obscured) coordinate only | ✔ |
| 25 | longitude | DOUBLE | `geojson.coordinates[0]` | GeoJSON order is [lng, lat] | ✔ |
| 26 | positional_accuracy | TEXT | `positional_accuracy` | int → string; null → `''` | ✔ |
| 27 | private_place_guess | TEXT | — **never requested** | always NULL (geoprivacy rule). **⚠ Flag D** | n/a |
| 28 | private_latitude | TEXT | — **never requested** (`private_geojson`) | always NULL | n/a |
| 29 | private_longitude | TEXT | — **never requested** (`private_location`) | always NULL | n/a |
| 30 | public_positional_accuracy | TEXT | `public_positional_accuracy` | int → string; null → `''` | ✔ |
| 31 | geoprivacy | TEXT | `geoprivacy` | null → `''` | ✔ |
| 32 | taxon_geoprivacy | TEXT | `taxon_geoprivacy` | null → `''` | ✔ |
| 33 | coordinates_obscured | TEXT | `obscured` | bool → `'true'`/`'false'` | ✔ (all `false` in sample) |
| 34 | positioning_method | TEXT | — **not in v2 schema** | `''`. **⚠ Flag E** | n/a |
| 35 | positioning_device | TEXT | — **not in v2 schema** | `''`. **⚠ Flag E** | n/a |
| 36 | species_guess | TEXT | `species_guess` | null → `''` | ✔ |
| 37 | scientific_name | TEXT | `taxon.name` | no taxon → `''` | ✔ |
| 38 | common_name | TEXT | `taxon.preferred_common_name` | missing → `''` (anonymous requests get the English name) | ✔ |
| 39 | iconic_taxon_name | TEXT | `taxon.iconic_taxon_name` | missing → `''` | ✔ |
| 40 | taxon_id | INT | `taxon.id` | no taxon → NULL | ✔ |

Requested but **not stored**: `place_ids` (PR3 scope check: must contain 141552) and `project_ids` (recorded in
evidence; empty for collection-project members).

## Flags for the author
- **A. time_zone.** v2 gives IANA names (`America/New_York`); the table holds Rails names. All 929 rows are
  `Eastern Time (US & Canada)`. Proposal: a small pinned lookup in `config/` (US zones + UTC). An unknown zone is
  stored as the raw IANA name and counted in PR3 evidence, never dropped.
- **B. updated_at disagrees in both directions.** For 416397971 the stored value (`23:59:01 UTC`) is *later* than
  v2's (`23:21:00 UTC`), so the export's `updated_at` is not the same clock as v2's. PR3 therefore detects
  "changed" by comparing the mapped row as a whole, not by `updated_at >` alone.
- **C. sound_url, tag_list.** The mapping follows the schema but no sample row had sounds or tags. These are
  marked unverified until a fixture contains one.
- **D. private_* columns.** Existing rows hold `''`; the agent writes NULL (CLAUDE.md rule). Both mean "not
  stored". Existing rows are left as they are unless you ask (the UPDATE would be shown first).
- **E. positioning_method/device** are not in the v2 Observation schema. The agent writes `''`, matching all 929
  existing rows.
- **F. id is signed INT** (max 2,147,483,647). Current ids are ~416 M, so there is ample headroom; noted only.
