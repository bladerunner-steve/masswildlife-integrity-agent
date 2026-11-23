# Project Brief

Part A is the author's original specification, verbatim. Part B records findings and decisions made
since, which refine Part A. Where they differ, **Part B wins**.

---

## Part B — Findings and decisions (Phase 0, 2026-11-23)

### Confirmed decisions
| Topic | Decision |
|---|---|
| Project | iNaturalist project **46777**, slug `masswildlife-s-all-wildlife-biodiversity-project`, title "MassWildlife's All Wildlife Biodiversity Project". Single title-search match. |
| Request scope | Request uses `project_id=46777`. `place_id` stays in `forbidden_params`. |
| PR3 scope check | 46777 is an **umbrella** project, so observations never list it in `project_ids`. PR3 accepts a record only if `place_ids` contains the pinned **scope place 141552** (custom place with the same name as the project). Otherwise reject with `out_of_policy_scope`. |
| Policy additions | `source.project.id: 46777`, `source.project.slug: masswildlife-s-all-wildlife-biodiversity-project`, `source.project.scope_place_id: 141552`. Verifier layer B checks all three. |
| Window field | `created_at`, filtered with `created_d1` / `created_d2`. |
| Repo location | `%USERPROFILE%\projects\masswildlife-integrity-agent` (outside OneDrive, because sync conflicts with WORM read-only/ACLs and would upload keys and vault). |
| Seed data | Copied to `data/source/MassWildlife.csv` + `README.txt` (gitignored: contains observer names). **Superseded 2026-11-23:** author says to ignore this CSV; the agent populates `masswildlife.inaturalist` incrementally from the v2 API. The CSV's 40 columns still document the table's column meanings. |
| Target table | `masswildlife.inaturalist`. At inspection it had 0 rows, no keys, `id` TEXT and wrong types. The 929-row CSV import landed in a separate table `observations-820625`. |
| Truncated trace | Decided 2026-11-23 (Phase 5): ground truth label **insufficient**; verifier verdict INSUFFICIENT EVIDENCE (`config/verifier.yaml: truncated_trace`). |
| Eval backend | Decided 2026-11-23: eval traces use offline in-memory DB stores (no MySQL writes), the test vault area only, a throwaway eval notary key, and recorded fixtures plus synthetic observations served by a fake API. |
| Verifier trust inputs | Approved 2026-11-23: the verifier also reads its own pins (`config/verifier.yaml`). Layer C never returns FAILED. A gate-blocked run is red. |

### Environment
- Python: no interpreter on PATH. The venv `.venv/` was created from `%USERPROFILE%\.conda\envs\jupyterlab-env\python.exe` (3.14.6). Always use `.venv\Scripts\python.exe`.
- Git: `C:\Program Files\Git\cmd\git.exe`. MySQL80 Windows service is running; client at `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe`.
- Shell: Windows PowerShell 5.1 (no `&&`). Code must stay cross-platform (pathlib, no shell tricks).

### Seed export facts (`data/source/MassWildlife.csv`)
- Export query: `quality_grade=any&identifications=any&place_id=141552&verifiable=true&spam=false`.
- 40 columns: id, uuid, observed_on_string, observed_on, time_observed_at, time_zone, user_id, user_login, user_name, created_at, updated_at, quality_grade, license, url, image_url, sound_url, tag_list, description, num_identification_agreements, num_identification_disagreements, captive_cultivated, oauth_application_id, place_guess, latitude, longitude, positional_accuracy, private_place_guess, private_latitude, private_longitude, public_positional_accuracy, geoprivacy, taxon_geoprivacy, coordinates_obscured, positioning_method, positioning_device, species_guess, scientific_name, common_name, iconic_taxon_name, taxon_id.
- 126,361 rows, 0 duplicate ids, max id 416484113, created_at 2012-04-10 → 2026-11-23 04:36:19 UTC (format `YYYY-MM-DD HH:MM:SS UTC`).
- `private_place_guess`, `private_latitude`, `private_longitude` always empty. 2,089 rows have geoprivacy `obscured` and 2,502 have `coordinates_obscured=TRUE`. Store only public coordinates; private_* must stay NULL.
- `MassWildlifeTEST.csv` (one row) stays in the OneDrive folder and was not copied.

### iNaturalist v2 facts (verified against `https://api.inaturalist.org/v2/api-docs`, OpenAPI 3.0, API 2.2.0, plus live probes)
- `GET /v2/observations` params include: `project_id`, `place_id`, `created_d1`, `created_d2`, `created_on`, `updated_since`, `id_above`, `id_below`, `order_by` (enum: created_at, geo_score, id, observed_on, random, species_guess, updated_at, votes), `order` (asc|desc), `page`, `per_page`, `fields`, plus location params lat/lng/radius/nelat/nelng/swlat/swlng.
- `fields` syntax, verified live: `fields=(id:!t,uuid:!t,created_at:!t,project_ids:!t,place_ids:!t)`. Nested fields look like `user:(login:!t)`.
- `/v2/observations/deleted` exists.
- `created_d1`/`created_d2`: ISO date-time (`Z` or offset), second precision, **inclusive at both ends** (so consecutive windows share a boundary second; dedupe by id). `per_page=200` accepted.
- v2 `Observation` has no `positioning_method`/`positioning_device`. v2 timestamps are local-offset ISO; the table stores `YYYY-MM-DD HH:MM:SS UTC`. Full mapping and flags: `docs/FIELD_MAPPING.md`.
- Observation schema fields relevant to the table: id, uuid, created_at, updated_at, observed_on, observed_on_string, time_observed_at, time_zone_offset, observed_time_zone, user{id,login,name}, quality_grade, license_code, uri, photos, sounds, tags, description, num_identification_agreements, num_identification_disagreements, captive, oauth_application_id, place_guess, geojson, location, positional_accuracy, public_positional_accuracy, geoprivacy, taxon_geoprivacy, obscured, taxon{id,name,preferred_common_name,iconic_taxon_name}, species_guess, place_ids, project_ids, private_geojson/private_location (never store these).
- Live probe (last 24 h, 2026-11-23): `project_id=46777` → 942 results and `place_id=141552` → 942 results. Every record's `place_ids` contained 141552. `project_ids` held only traditional projects (e.g. 86450) or was empty.
- The 15 sub-projects are collections, each scoped to one WMA place: 46521→141166, 46523→141168, 46530→141169, 46656→141170, 46659→141171, 46756→141181, 46759→141174, 46761→141179, 46763→141176, 46764→141178, 46767→141173, 46768→141177, 46769→141175, 46771→141180, 46775→141551.
- `GET /v1/projects/{ids}` returns 422 "Too many IDs" above about 10 ids per call.

---

## Part A — Original specification (verbatim from the author)

You are helping me build the research prototype for my capstone, "Verifying the Integrity of Agentic Intelligence" (University of Arizona; advisor Dr. Dalal Alharthi). It is a locally run, scheduled agent that pulls new iNaturalist observations into MySQL. Every step it takes leaves a tamper-evident, signed provenance receipt, stored in a local write-once vault. A verifier checks those receipts at three levels (cryptographic, policy, evidence) and shows the result to the user as an integrity badge.

The design builds on Dr. Alharthi's provenance-native receipts: Merkle-linked, Ed25519-signed records emitted at every module boundary, rooted in a signed Minimal Specification (PR0). It is the local equivalent of her AWS architecture: Notary Lambda + KMS becomes a local notary process, S3 Object Lock in Compliance Mode becomes a local WORM vault, and Aurora becomes a MySQL provenance index. My own contribution is the research question:

To what extent does policy- and evidence-aware verification reduce false integrity assurances compared with cryptographic receipt verification alone?

So the code has to support (a) a real daily production run and (b) a controlled evaluation that compares three verifier configurations on identical, labeled traces.

### How I want you to work
Plan first. Before writing code, read this whole prompt, inspect my environment (Phase 0), and show me a short implementation plan with the repo layout. Wait for my OK on the plan.
Work in the phases below. Stop at each checkpoint, show me what works (tests, sample output), and wait before moving on.
Database access is least-privilege by design. The agent connects as MySQL user claude, which has only SELECT, INSERT and UPDATE on masswildlife.*. It cannot CREATE, ALTER, DROP, DELETE or TRUNCATE, and you must not ask me to widen its grants. Any table or index the system needs goes in a numbered DDL script under sql/admin/ (for example sql/admin/001_provenance_index.sql), written to be idempotent (CREATE TABLE IF NOT EXISTS), with a header comment explaining it. I run these scripts myself as a MySQL admin. Tell me when one is ready and wait until I confirm it ran. Never write code that needs DELETE: corrections are UPDATEs or new rows, and the grant itself is part of the policy (below).
Ask before rewriting existing data. Show me the exact SQL before anything that changes existing rows in masswildlife.inaturalist beyond the normal upsert.
Don't trust your memory of APIs. Check iNaturalist v2 parameter and field names against https://api.inaturalist.org/v2/docs/ (fetch it, or ask me to paste the relevant section). Check library calls against current docs. My proposal requires this, because AI can produce outdated calls.
Comment your code for AI disclosure. Every module gets a header comment saying what it does, that it was AI-assisted, and how it was verified (which test covers it). Keep a running docs/AI_USAGE.md log of what you generated and what I reviewed. My proposal's AI-disclosure section requires both.
Python 3.11+. Use a virtual environment and pin dependencies in requirements.txt. Suggested libraries (confirm current versions): requests, PyMySQL or mysql-connector-python, cryptography (Ed25519), rfc8785 (JSON canonicalization), python-dotenv, pydantic or jsonschema, PyYAML, pytest, jinja2 (badge report). Use boto3 only for the optional S3 backend.
Must run on Windows and Linux/macOS. Use pathlib everywhere and no shell-specific tricks in the core code.

### Secrets and the iNaturalist token (non-negotiable)
Read all secrets from environment variables, loaded from a .env file in the project root. Create .env.example with placeholder values only, and add .env, keys/, vault/, *.pem and *.key to .gitignore before the first commit. This will become a public GitHub repo.
Variables: INAT_API_TOKEN (optional, see below), MYSQL_HOST, MYSQL_PORT, MYSQL_USER=claude, MYSQL_PASSWORD, MYSQL_DATABASE=masswildlife, NOTARY_KEY_PASSPHRASE. Never print or log MYSQL_PASSWORD. Ask me to fill .env myself rather than asking for the values in chat.
Never print, log, hash into a receipt, or commit the token. Receipts may record auth_mode: "token" | "anonymous" and the token's expiry time, nothing more.
Tokens expire after about 24 hours. On each run, decode the JWT exp claim (no signature check needed, it's only for scheduling). If the token is missing, expired, or expires within 1 hour:
- Reading public observations does not require auth, so fall back to anonymous requests if the policy allows it (auth.allow_anonymous: true, which is the default). Record auth_mode: "anonymous" and the reason in the receipt.
- Write a clear "token needs refresh" warning to the run report and the badge page.
- Note in the README that the reliable automated refresh path is an iNaturalist OAuth application. Implement that only if I ask. The manual path is to paste a new token into .env from https://www.inaturalist.org/users/api_token.

Geoprivacy. If a token returns private or true coordinates for obscured or sensitive taxa, never write them to public outputs (badge pages, example reports, the repo). Store only the fields the existing table already uses.

### The production workflow (what runs daily)
Implement the agent as a pipeline of six modules. Each one has a declared input/output contract, and each emits exactly one receipt at its boundary:

| Step | Receipt | Module | What it does |
|---|---|---|---|
| 0 | PR0 | plan generation | Builds the run's Minimal Specification: run id, the time window, the declared step sequence, the policy hash, expected module measurements, and the notary key id. The notary signs it before any execution. It is the genesis of the chain. |
| 1 | PR1 | API request | Builds the exact iNaturalist request(s) from the plan. It runs the pre-execution policy gate, then records the full request (URL, params, headers minus auth). |
| 2 | PR2 | API response | Executes the request(s) with pagination. Stores each raw response body as an evidence object and records status codes, total_results, page count and timing. |
| 3 | PR3 | filtering logic | Decides which observations are new: inside the window, actually in the project, not already in MySQL (or changed). Records a per-observation decision list with a reason code. |
| 4 | PR4 | database update | Upserts into masswildlife.inaturalist in one transaction. Records the DB user, the SQL operation types used, rows inserted/updated/skipped, and a hash of the rows read back after commit. |
| 5 | PR5 | completion decision | Reconciles counts across steps, decides success, partial or failed, and closes the run. Then the notary seals it with the Merkle root (below). |

The policy (what counts as "new" and "allowed") lives in config/policy.yaml. It is hashed into PR0, so changing it is visible in the receipts:

```yaml
policy_version: 1
source:
  host: api.inaturalist.org
  endpoint: /v2/observations          # verify the path in the v2 docs
  method: GET
  project:
    title: "MassWildlife's All Wildlife Biodiversity Project"
    id: <PINNED_NUMERIC_ID>             # resolve once in Phase 0, then pin it
    slug: <PINNED_SLUG>
  forbidden_params: [place_id, lat, lng, radius, nelat, nelng, swlat, swlng, user_id]  # location or scope overrides
window:
  max_hours: 24
  grace_minutes: 15                    # tolerance for scheduler jitter
  field: created_at                    # "new" = created in window; confirm with me (created_at vs observed_on vs updated_at)
database:
  target: masswildlife.inaturalist
  user: claude                                  # the only DB account the agent may use
  allowed_operations: [SELECT, INSERT, UPDATE]   # matches the MySQL grant; no DELETE/DROP/ALTER/TRUNCATE/CREATE
auth:
  allow_anonymous: true
rate_limit:
  max_requests_per_minute: 60          # iNaturalist asks for <=1 req/s; also be well under the daily cap
  per_page: 200
```

Policy enforcement has two parts.

- The pre-execution gate (PR1). If the request targets a different project, adds any location parameter, uses a window over 24 h (plus grace), hits another host or endpoint, or uses a non-GET method, then the agent does not send it. It emits a signed PR1 receipt with policy_decision: "violation" and the list of rule ids violated, goes straight to PR5 with failed, and flags me. Flagging means a red badge, a line in reports/ALERTS.md, a non-zero exit code, and a desktop notification if it's easy on the OS. This is the "someone changed the query to another location" case.
- The post-response check (PR3). Every returned observation must list the pinned project id in its project membership field and have its timestamp inside the window. Out-of-scope records are rejected with reason out_of_policy_scope, never inserted, and counted. Any count above zero is flagged. *(Refined in Part B: membership is proven by `place_ids ∋ 141552`.)*

Add an evaluation-only flag, --unsafe-bypass-gate, that lets an out-of-policy request through while still producing correctly signed receipts. It must refuse to run against the production vault or the production database: it requires --vault test and a test DB. This is how I generate validly signed but unauthorized runs, which is the core case where crypto-only verification gives false assurance.

Incremental logic. Use the window [last_successful_run.window_end, now], capped at 24 h + grace. On the first run, use now - 24h. Use the API's date-filter parameters for created_at (check the exact names in the v2 docs). v2 requires an explicit fields parameter, so request only the fields the table needs plus project membership. Order by id and paginate until it is exhausted. Deduplicate by observation id. Upserts must be idempotent, so re-running the same window changes nothing. Use INSERT ... ON DUPLICATE KEY UPDATE (this needs only INSERT and UPDATE privileges and a unique key on the observation id). Never use REPLACE INTO, because it deletes then inserts and the claude user has no DELETE.

### Phase 0: Discover my environment (read-only)
- Inspect MySQL (read-only, as user claude): run SHOW GRANTS FOR CURRENT_USER() and confirm it shows only SELECT, INSERT, UPDATE on masswildlife.*; if it shows more, stop and tell me. Then run SHOW CREATE TABLE masswildlife.inaturalist, get the row count, and pull 5 sample rows. Note the primary key and any unique keys, and the max created_at / id.
- Inspect ./data/source/. This is the export from iNaturalist that seeded the table (CSV or similar). Infer column meanings.
- Build the field mapping. Write a mapping table in docs/FIELD_MAPPING.md: each table column, the matching iNaturalist v2 field path, its type, and any transform. Flag columns you can't map. Do not change the existing table's columns. If a unique key on the observation id is missing, write the ALTER as an admin script in sql/admin/ (it must first check for duplicate ids with a SELECT, and report them rather than delete them) and wait for me to run it.
- Pin the project. Resolve the project via the iNaturalist projects endpoint by title search. Show me the candidate id(s), slugs, titles, and the project's place/rules. I'll confirm, then you pin the id and slug in policy.yaml.
- Write the admin DDL scripts. These are the tables the claude account can't create itself:
  - sql/admin/001_provenance_index.sql: the local Aurora equivalent, masswildlife.provenance_index, with run_id, step, step_type, module, agent_id, timestamp, receipt_hash, signature, vault object key, and verification_status, plus a unique key on (run_id, step). The verifier updates verification_status with UPDATE only.
  - sql/admin/002_run_state.sql: masswildlife.agent_run_state holding each run's window_start/window_end/status, so the incremental window can be read with SELECT.
  - sql/admin/003_test_table.sql: CREATE TABLE IF NOT EXISTS masswildlife.inaturalist_test LIKE masswildlife.inaturalist, for test runs. Since claude cannot DELETE or TRUNCATE, test runs must use a fresh run_id-scoped approach or I re-run a reset script (sql/admin/900_reset_test.sql) as admin.
  - sql/admin/README.md: the run order and the one-line mysql -u <admin> -p < file.sql command for each script. Tell me when they're ready, and wait until I confirm I ran them. Treat this index as an untrusted convenience. The verifier must never rely on it, only on the vault.

Checkpoint 0: show me the schema findings, the field mapping, the project candidates, and the proposed DDL.

### Phase 1: Receipts and the digital notary
Receipt body (from Listing 1 of Dr. Alharthi's paper, extended):

```json
{
  "schema": "receipt/v1",
  "run_id": "<uuid>",
  "step": 3,
  "step_type": "filtering",
  "module": "M3:filter",
  "model_id": "deterministic-filter-v1",
  "agent_id": "sha256(code_digest | tool_manifest_digest | policy_digest | notary_key_id)",
  "in_hash": "sha256(canonical input)",
  "out_hash": "sha256(canonical output)",
  "evidence": [{"key": "<vault object key>", "sha256": "...", "role": "input|output|raw_response|decision_list"}],
  "spec_hash": "sha256(PR0 body)",
  "prev_hash": "receipt_hash of step-1 (PR0's prev_hash = previous run's seal hash, or 64 zeros for the first run)",
  "policy_decision": "pass|violation|n/a",
  "policy_rules_evaluated": ["..."],
  "nonce": "<128-bit random hex>",
  "timestamp": "<RFC 3339 UTC>",
  "notary_key_id": "<sha256 of public key, first 16 hex>"
}
```

- receipt_hash = SHA-256(JCS(body)), using RFC 8785 JSON canonicalization. signature = Ed25519_sign(notary_key, JCS(body)). Store {body, receipt_hash, signature} as the receipt object.
- The measurement. agent_id is a digest over the actual module source files, the tool manifest (allowed endpoints and DB ops), the policy file, and the notary key id, computed at runtime. PR0 declares the expected measurement for each module, and the verifier rejects mismatches.
- The Merkle link. Receipts form a hash chain through prev_hash. At PR5, the notary also builds a binary Merkle tree over all receipt hashes in the run and signs a run seal {run_id, merkle_root, receipt_count, head_hash, prev_seal_hash}. Store the seal in the vault. Chaining prev_seal_hash across days links runs into one continuous log.
- Separation of duties. The notary is a separate process, a small local HTTP service bound to 127.0.0.1 or a subprocess CLI, and it is the only component that can read the private key. Agent modules send it bodies and get back signatures, and they never touch the key. Store the private key encrypted (PKCS#8 with NOTARY_KEY_PASSPHRASE) under keys/ with restrictive permissions (chmod 600, or an icacls ACL on Windows). Commit only the public key, under keys/public/. Provide notary keygen and notary rotate commands; rotation keeps old public keys so old receipts stay verifiable.

Checkpoint 1: unit tests for canonicalization stability, sign/verify, chain building, Merkle root and inclusion proofs, and measurement.

### Phase 2: The local WORM vault (S3 Object Lock Compliance Mode equivalent)
Build a vault behind a VaultBackend interface with two implementations:

- LocalWormVault (default). It emulates S3 Object Lock in Compliance Mode on the local filesystem:
  - Content-addressed, write-once objects. The key is runs/<date>/<run_id>/<step>-<type>.json plus an object at objects/sha256/<hash>. put fails if the key exists. There is no overwrite or delete API at all.
  - Per-object retention metadata. Store retain_until (default 365 days, configurable, and it can only be extended, never shortened) and mode: COMPLIANCE. This mirrors the S3 semantics: in compliance mode nobody, not even root, can shorten retention or delete before retain_until.
  - After writing, mark files read-only (chmod 444 on POSIX; attrib +R plus an icacls deny-delete ACE for the current user on Windows).
  - An append-only vault ledger (vault/LEDGER.jsonl). Each line is a put event with object hash, key, time, and the previous ledger line's hash, so the ledger is itself hash-chained.
  - Be honest about limits in the README. A local admin can still delete files. What we guarantee is tamper-evidence, not tamper-proofing. To make deletion or rollback detectable, add an external anchor: after each run, append the seal hash to anchors/anchors.txt and commit it to a separate git repo (or print it to a file I can email to myself). The verifier checks that the vault's latest seal matches the latest anchor.
- S3ObjectLockVault (optional, same interface). Uses boto3 with ObjectLockMode=COMPLIANCE and ObjectLockRetainUntilDate. It works against real AWS S3, or a local S3-compatible server that supports Object Lock if I choose to run one. Keep this stub-tested only unless I ask, but the interface must make switching a config change.

Also write every receipt to masswildlife.provenance_index after it is safely in the vault.

Checkpoint 2: tests showing overwrite and delete attempts are refused, retention can't be shortened, ledger tampering is detected, and an anchor mismatch is detected.

### Phase 3: Wire up the real pipeline
Implement the six modules and an agent run command with these flags: --dry-run (no DB writes, but still receipted), --vault prod|test, --db prod|test, and --window-hours N (the policy gate still applies).
Use a lock file to prevent overlapping runs. Retry with backoff on HTTP 429/5xx and respect rate limits. Send a descriptive User-Agent such as masswildlife-integrity-agent/0.1 (no personal email).
Every run writes reports/runs/<run_id>/report.json and calls the verifier at the end (Phase 4) to produce the badge.
Record fixtures. Save a few real API responses (with geoprivacy-safe fields only) under tests/fixtures/ so tests run offline.

Checkpoint 3: one real --dry-run, then one real run against the test copy masswildlife.inaturalist_test (created by my admin script 003_test_table.sql). Show me the receipts and the reconciliation numbers.

### Phase 4: The verification framework and the integrity badge
Build verify as a separate, read-only CLI. Its only inputs are the vault, the trusted public key(s), and the anchors file. It never uses the agent's code paths for its decisions, and never uses the MySQL index. It has three layers, which you can switch on cumulatively with --mode crypto | crypto+policy | crypto+policy+evidence (configurations A, B and C):

A. Cryptographic receipt verification. Each signature verifies against a trusted key. receipt_hash recomputes. prev_hash links are unbroken and in step order, and PR0's prev matches the previous seal. Nonces are unique. spec_hash equals the hash of PR0. Evidence objects re-hash to their recorded hashes, and in_hash/out_hash match the evidence. The Merkle root and seal verify. Measurements match PR0's declared values. The vault ledger and the external anchor agree. Localize the first failing step and module.

B. Policy-aware verification. Re-evaluate the policy from PR0 (as signed, not as it is on disk now) against the recorded request and decisions. Check that the project id and slug equal the pinned values, that there are no forbidden or location params, the window is ≤ 24 h + grace, the host/endpoint/method are allowed, the DB user recorded in PR4 is claude, and the DB operations are within the allowed set. Check that the executed step sequence equals PR0's declared sequence (no skipped, reordered or extra steps), and that no out-of-scope observation reached PR4. A run whose receipts are perfectly signed but whose request violated policy must fail here.

C. Evidence-aware verification. Check that every mandatory evidence object for each step exists (raw response per page, decision list, DB readback hash, reconciliation). Check that counts reconcile: total_results ≥ fetched; fetched = accepted + rejected-by-reason; accepted = inserted + updated + skipped; DB readback hash = PR4's out_hash. Check that no pages are missing, response timestamps and observation timestamps are fresh (inside the window), and the completion decision is consistent with the evidence. If evidence is missing or stale, or contradicts itself without proving tampering, the result is insufficient, not failed.

Outcome rules (exactly three statuses, per my paper):
- VERIFICATION FAILED. Any crypto failure, any policy violation, or contradictory evidence that proves a false claim.
- INSUFFICIENT EVIDENCE. Crypto and policy pass, but required evidence is missing, stale, or unreconcilable.
- VERIFIED WITHIN SCOPE. All enabled layers pass.

The badge text must state the scope: it attests the run was untampered, plan-conformant and policy-compliant, with sufficient recorded evidence. It does not attest that the observations are factually correct. Configurations A and B can only ever output what their layers can see. Record which configuration produced each verdict.

The user-facing badge.
- A self-contained reports/runs/<run_id>/badge.svg with green, red, or amber and the status label.
- reports/runs/<run_id>/index.html (Jinja2, no external network calls). It shows the status, a one-line plain-language explanation, the scope statement, the run window, counts, and a step-by-step table (PR0–PR5 with a check or cross per layer). On failure it shows the localized step and the reason, and a "token needs refresh" banner when applicable.
- reports/index.html lists all runs with their badges, newest first.
- verify --json prints machine-readable results for the evaluation harness.
- Keep the wording interpretable for a non-cryptographer. I'll be evaluating the badge for interpretability, accuracy, consistency and failure modes.

Checkpoint 4: verify a clean real run (should be green), then demonstrate one red and one amber case.

### Phase 5: Evaluation harness (for the paper)
Build eval/ to generate independently labeled scenarios in the test vault, from recorded fixtures plus synthetic runs, never touching production. Cover these cases:

| Scenario | Ground-truth label | Expected: A / B / C |
|---|---|---|
| clean authorized run | legitimate | V / V / V |
| naive artifact tamper (evidence changed, receipt not) | tampered | F / F / F |
| log-rewriting (artifact + recorded hash changed) | tampered | F / F / F |
| forward-recompute (chain rebuilt from the tampered step, unsigned or self-signed) | tampered | F / F / F |
| key-forgery (re-signed with a non-trusted key) | tampered | F / F / F |
| signed but unauthorized: other place/project or location params, via --unsafe-bypass-gate | policy violation | **V** / F / F |
| plan deviation: skipped or reordered step, validly signed | policy violation | **V** / F / F |
| window > 24 h, validly signed | policy violation | **V** / F / F |
| omitted evidence: a raw page missing, validly signed | insufficient | **V** / **V** / I |
| unreconcilable counts, validly signed | insufficient | **V** / **V** / I |
| truncated trace (no PR5/seal) | insufficient/tampered (decide with me) | ? |
| replayed receipt from another run | tampered | F / F / F |

(V = VERIFIED WITHIN SCOPE, F = VERIFICATION FAILED, I = INSUFFICIENT EVIDENCE.) The bold cells are the false assurances the research question measures. Don't hard-code the expected cells into the verifier. They are ground truth for scoring only.

Compute the following and write CSVs plus a short markdown summary to eval/results/:
- false-assurance rate per configuration (primary metric)
- violation-detection precision, recall and F1
- false alarms on legitimate runs
- insufficient-evidence recognition rate
- localization accuracy
- per-trace verification latency (mean, p95 over N repeated trials)
- per-receipt build and verify time
- receipt and storage overhead

Include confusion matrices with denominators, and repeat each scenario N times (configurable, default 30) with fresh nonces. Do not write anticipated results anywhere. Only measured numbers go in the output.

Checkpoint 5: run the full matrix and show me the summary table.

### Phase 6: Scheduling (once every 24 hours)
Provide scripts/run_daily.ps1 (Windows) and scripts/run_daily.sh (Linux/macOS). Each one activates the venv, runs agent run --vault prod --db prod, then runs verify, and appends to logs/agent-YYYYMMDD.log. Both scripts exit non-zero on a red or amber result. Document the following in the README:
- Windows Task Scheduler. Use the `schtasks /Create /SC DAILY /ST 06:00 /TN "MassWildlife Integrity Agent" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File <path>\scripts\run_daily.ps1"` form, and also the GUI steps. Tick "Run task as soon as possible after a scheduled start is missed" (StartWhenAvailable), choose "Run whether user is logged on or not", and set "Do not start a new instance" if one is already running.
- cron. `0 6 * * * cd /path/to/project && ./scripts/run_daily.sh >> logs/cron.log 2>&1`. Note that macOS may need Full Disk Access for cron, or a launchd plist instead (provide one).
- A missed day is handled by the window logic: the next run catches up to 24 h + grace and flags any uncovered gap rather than silently widening the window.

### Phase 7: Repo hygiene and docs
- README.md covers the architecture diagram (a Mermaid diagram of the local equivalents of Execution → Capture → Notary → Vault → Index → Verifier), setup, .env setup, the token refresh guidance, how to run, how to verify, how to reproduce the evaluation, and the honest limits of the local WORM vault.
- docs/VERIFICATION_METHODOLOGY.md covers the threat model, from naive through log-rewriting and forward-recompute to key-forgery. Assume the adversary may control any strict subset of agent stages but not both the notary key and the offline verifier. It also covers the trust assumptions, the three layers, the decision rules, and the non-goals (no claim about factual correctness or hidden reasoning).
- docs/AI_USAGE.md and docs/FIELD_MAPPING.md (from earlier phases).
- examples/ holds badge outputs from synthetic runs only, safe to publish.
- Run a pre-commit check that fails if anything resembling a JWT, a private key, or a .env is staged.
