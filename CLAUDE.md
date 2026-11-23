# CLAUDE.md — MassWildlife Integrity Agent

Capstone research prototype. The scheduled agent ingests iNaturalist observations into MySQL and
emits Ed25519-signed, Merkle-linked provenance receipts (PR0–PR5) into a local WORM vault. A 3-layer
verifier (crypto / policy / evidence, configs A/B/C) produces an integrity badge, and an eval harness
measures false-assurance rates.

**Read `docs/PROJECT_BRIEF.md` before doing anything.** Part A is the full spec. Part B holds
confirmed decisions and verified API facts, and overrides Part A.

## Current status (update this section at every checkpoint)
- Phase 0, in progress. Done: repo + `.gitignore` + `.env.example`, `.venv` (Python 3.14.6) with
  pinned `requirements.txt`, seed CSV in `data/source/`, project resolved (46777 / scope place 141552),
  v2 API params verified, `scripts/phase0_inspect_db.py` written, `docs/AI_USAGE.md` started.
- DB inspected 2026-11-23: grants OK (`claude`@`%`: SELECT, INSERT, UPDATE on `masswildlife.*` + USAGE).
  `masswildlife.inaturalist` is **empty (0 rows), has no PK/unique key, `id` is TEXT, and several column types
  are wrong** (e.g. user_name/updated_at/quality_grade/url/geoprivacy/species_guess BIGINT, common_name
  BINARY(1), iconic_taxon_name GEOMETRY): looks like a failed import wizard. A second table
  `observations-820625` holds 929 rows (ids 416380763–416484113, created_at 2026-11-22 19:19 → 2026-11-23
  04:36 UTC, sane types, no keys, private_* empty).
- Author decision 2026-11-23: target is `masswildlife.inaturalist`; ignore the 126k seed CSV
  (`data/source/`); the agent fills the table incrementally from the v2 API. Author believed the 929-row CSV
  was loaded into `inaturalist`, but it is in `observations-820625` (re-checked: inaturalist = 0 rows).
- Author rebuilt `inaturalist` themselves: `id INT NOT NULL` PK, sane types, 929 rows (no 004 script needed).
- Written: `docs/FIELD_MAPPING.md` (live diff 48 rows OK; flags A–F), `config/policy.yaml`,
  `sql/admin/001,002,003,900` + `README.md`.
- Checkpoint 0 passed (author ran 001–003, approved flags A–F).
- Phase 1 built: `mwia.common` (JCS, Merkle RFC 6962, receipt/seal schema + verify, measurement, keyring),
  `mwia.notary` (keys, service, stdio client, CLI), `config/tool_manifest.yaml`. `pytest`: 111 passed.
  Notary = subprocess over stdin/stdout; it enforces schema, key id and chain linkage, and seals from its own
  record. It does not enforce plan conformance (by design: layer B must catch that). PR0.spec_hash = null.
- Checkpoint 1 passed. Real notary key `a62a04bf20ca2931` created (CLI needs `$env:PYTHONPATH="src"` until Phase 3
  adds an entry point).
- Phase 2 built: `mwia.vault` (VaultBackend with shared put/verify logic; LocalWormVault with xb writes,
  read-only + deny ACEs, msvcrt/fcntl lock, LEDGER.jsonl hash chain, vault.json retention floor;
  S3ObjectLockVault stub-tested; AnchorLog + check_anchors), `mwia.index` (SQL guard, provenance_index
  insert-after-vault, verification UPDATE), `config/settings.yaml`. `pytest`: 183 passed, plus the live DB test
  (MWIA_DB_TESTS=1) passed once, leaving 1 env='test' row in provenance_index.
- Checkpoint 2 passed.
- Phase 3 built: `mwia.agent` (M0–M5 + pipeline, gate, transform, stores, HTTP, auth), `scripts/mwia.py` CLI
  (`agent run`, `notary ...`), redacted fixtures. `pytest`: 230 passed. Live: dry run `--vault test --db prod`
  (942 fetched, 925 unchanged/4 changed/13 new vs the 929 rows), real run `--vault test --db test` (942 inserted),
  plus two idempotency re-runs. The prod `vault/` and `anchors/` don't exist yet; prod `inaturalist` is untouched.
- Bypass design: `--unsafe-bypass-gate` makes PR1 record "pass" (a simulated compromised gate) while the
  real params are recorded, so verifier layer B must catch it from evidence.
- Checkpoint 3 passed; bypass semantics approved.
- Phase 4 built: `mwia.verify` (read-only reader, layers A/B/C, engine with 3 statuses, badge SVG + Jinja2
  pages + reports/index.html, CLI `scripts/mwia.py verify`), `config/verifier.yaml` (independent pins;
  truncated_trace = insufficient until Phase 5). The pipeline calls the verifier (config C) after every run.
  `pytest`: 252 passed. Live test-env demos: green, red (bypass place_id=1: A=V, B/C=F) and amber (omitted
  page: A/B=V, C=I).
- Eval note for Phase 5: a global ledger break fails every run in that vault, so each tampered trace needs
  its own vault directory.
- Checkpoint 4 passed; decisions 1–3 approved (verifier pins file, C never FAILED, gate-blocked run red).
- Phase 5 decisions: truncated trace = insufficient; eval uses offline in-memory stores (no MySQL).
- Phase 5 built: `eval/` (harness: per-trace vault, throwaway eval and attacker keys, fake API from fixtures +
  synthetic clones; 12 seeded scenarios; metrics; `eval\run_eval.py`). Full run: 360 traces, results in
  `eval/results/summary.md`. Run 1 archived (it exposed a layer-B bug on an omitted decision list, now fixed).
  The fixture observer `user.id` is now pseudonymized. `pytest`: 259 passed.
- Checkpoint 5 passed. Fixtures are kept with a CC BY-NC attribution note (tests/fixtures/README.md).
- Phase 6 built: `scripts/run_daily.ps1` (-Vault/-Db default prod), `scripts/run_daily.sh` (MWIA_VAULT/MWIA_DB
  default prod), `scripts/register_task.ps1` (StartWhenAvailable, IgnoreNew, 2 h limit; the author runs it),
  launchd plist, `docs/SCHEDULING.md` (to be linked from the README in Phase 7). Run state is now written after
  verification: only verified success advances the window. `pytest`: 264 passed. The scripts were tested on the
  test env only.
- Checkpoint 6 passed. First production run done 2026-11-23 (run e49daea7: 13 inserted, 5 updated, green).
  `vault/` and `anchors/` now exist (prod chain started). Task registration (`scripts\register_task.ps1`) is
  left to the author.
- Phase 7 built: README.md, docs/VERIFICATION_METHODOLOGY.md, examples/ (synthetic, from eval/make_examples.py),
  pre-commit secret check (`scripts/precommit_check.py`, `.githooks/pre-commit`, core.hooksPath set), hygiene
  test for AI-disclosure headers. `pytest`: 353 passed. A `--all` secret scan of what would be committed is clean.
- Checkpoint 7 passed. First commit `833065c` on main (135 files; pre-commit secret check passed), authored
  with the GitHub noreply address (repo-local `user.email`). Not pushed.
  A code licence is not chosen yet. Task registration is left to the author.
- Then: `docs/FIELD_MAPPING.md`, `config/policy.yaml` (pinned: project id 46777, slug
  `masswildlife-s-all-wildlife-biodiversity-project`, `scope_place_id: 141552`, window field `created_at`),
  `sql/admin/001_provenance_index.sql`, `002_run_state.sql`, `003_test_table.sql`, `900_reset_test.sql`,
  `004_unique_obs_id.sql` only if id has no PK/unique key, and `sql/admin/README.md` → **Checkpoint 0**.
- Later phases: 1 receipts+notary · 2 WORM vault+ledger+anchors · 3 pipeline (`agent run`) ·
  4 verifier+badge · 5 eval harness · 6 scheduling · 7 docs/hygiene. Stop at every checkpoint.

## Working rules (non-negotiable)
- **Checkpoints:** stop at each one, show tests/sample output, wait for the author's OK.
- **DB least privilege:** the agent connects as `claude` (SELECT, INSERT, UPDATE on `masswildlife.*` only).
  Never ask to widen grants. Never write code needing DELETE, TRUNCATE, DDL or `REPLACE INTO`. Upserts use
  `INSERT ... ON DUPLICATE KEY UPDATE`. Corrections are UPDATEs or new rows.
- **DDL:** goes only in numbered, idempotent `sql/admin/NNN_*.sql` files with a header comment. The author
  runs them as admin. Say when one is ready, then wait for confirmation.
- **Existing data:** show the exact SQL before changing existing rows in `masswildlife.inaturalist` beyond
  the normal upsert.
- **APIs:** don't trust memory. Check iNaturalist v2 against `https://api.inaturalist.org/v2/api-docs`
  (raw OpenAPI JSON; the `/v2/docs/` page is a JS Swagger UI). Check library calls against current docs.
- **Secrets:** all come from `.env` (python-dotenv). Never print or log `MYSQL_PASSWORD`. Never print, log,
  hash into a receipt, or commit `INAT_API_TOKEN` (receipts record only `auth_mode` and the token's exp).
  Never ask for secret values in chat; ask the author to edit `.env`.
- **Geoprivacy:** never store or publish private/true coordinates (`private_geojson`, `private_location`).
  `private_*` columns stay NULL.
- **AI disclosure:** every module starts with a header comment saying what it does, that it was
  AI-assisted, and how it was verified (which test). Append to `docs/AI_USAGE.md` each phase.
- **Verifier independence:** `mwia.verify` must not import `mwia.agent` or read the MySQL index. Its
  inputs are only the vault, trusted public keys and anchors. Re-evaluate policy from the signed PR0
  snapshot. Never hard-code expected eval outcomes; write only measured numbers.
- **Eval safety:** `--unsafe-bypass-gate` requires `--vault test` and the test DB.
- **Public repo:** this repo will be public. Commit only `keys/public/`. `data/`, `vault/`, `anchors/`,
  `reports/runs/` and `logs/` are gitignored. Commit only when the author asks.
- **Cross-platform:** use pathlib and no shell-specific tricks in core code. HTTP User-Agent is
  `masswildlife-integrity-agent/0.1` (no personal email). Rate limit ≤ 1 req/s.

## Environment
- Windows 11, PowerShell 5.1 (no `&&`; use `;` / `if ($?)`). Python: `.venv\Scripts\python.exe` only
  (nothing on PATH). Git: `C:\Program Files\Git\cmd\git.exe`.
  MySQL client: `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe` (service MySQL80).
- Install deps: `.venv\Scripts\python.exe -m pip install -r requirements.txt`. Pins are the newest release
  ≥14 days old. Optional S3 backend: `requirements-s3.txt` (boto3).
- Tests: `.venv\Scripts\python.exe -m pytest`.

## Planned layout
`config/` (policy.yaml, tool_manifest.yaml, settings.yaml) · `sql/admin/` · `src/mwia/{common,notary,vault,index,agent,verify}` ·
`templates/` (Jinja2 badge/report) · `eval/` · `tests/` (+`fixtures/`) · `scripts/` · `docs/` · `examples/` (synthetic only).
