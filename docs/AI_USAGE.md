# AI Usage Log

This project was built with AI assistance (Claude, via Claude Code). Every source file carries a
header saying what it does, that it was AI-assisted, and how it was verified. This log records what
the AI generated and what the author reviewed, phase by phase.

| Date | Phase | AI generated | Verified by | Author review |
|---|---|---|---|---|
| 2026-11-23 | 0 | Environment discovery (read-only): Python/MySQL/git location, seed CSV profile (126,361 rows, 0 dup ids, private_* empty), iNaturalist project resolution (46777 umbrella; place 141552), v2 parameter names checked against `https://api.inaturalist.org/v2/api-docs` (OpenAPI 3.0, API 2.2.0) and a live probe | Live API responses; spec JSON | Scope rule (query project 46777, check place 141552), window field `created_at`, repo location, confirmed by author |
| 2026-11-23 | 0 | `.gitignore`, `.env.example`, `requirements.txt` (pins = newest release ≥14 days old, checked on PyPI), `scripts/phase0_inspect_db.py` | Import check in venv; inspection script run at Checkpoint 0 | Checkpoint 0 approved |
| 2026-11-23 | 0 | `CLAUDE.md` (session rules + status), `docs/PROJECT_BRIEF.md` (verbatim spec + Phase 0 decisions/facts) for session handoff | n/a (docs) | Checkpoint 0 approved |
| 2026-11-23 | 0 | DB inspection findings: original `inaturalist` empty with wrong types and no key, so the author rebuilt it (PK on id, 929 rows). AI did not run any DDL. | `scripts/phase0_inspect_db.py` output (grants, schema, index, counts, samples) | Author rebuilt the table |
| 2026-11-23 | 0 | `docs/FIELD_MAPPING.md` (40 columns ↔ v2 paths + transforms, flags A–F) | Live diff: 48 stored rows re-fetched from v2, 35/35 columns matched except one observer-edited record | Checkpoint 0 approved |
| 2026-11-23 | 0 | `config/policy.yaml` (pins 46777 / slug / scope place 141552, allowed + forbidden params, forbidden private fields) | YAML parse; params checked in OpenAPI; live probe of `created_d1/d2` | Checkpoint 0 approved |
| 2026-11-23 | 0 | `sql/admin/001_provenance_index.sql`, `002_run_state.sql`, `003_test_table.sql`, `900_reset_test.sql`, `sql/admin/README.md` | Author reviews and runs as admin; `SHOW TABLES` / `SHOW CREATE TABLE` afterwards | Checkpoint 0 approved |

| 2026-11-23 | 0 | Checkpoint 0 closed: author ran 001–003; tables and keys confirmed with SHOW TABLES / SHOW INDEX as `claude` | Read-only queries | Author approved mapping flags A–F |
| 2026-11-23 | 1 | `src/mwia/common/{canonical,timeutil,merkle,keyring,receipt,measure}.py`, `src/mwia/notary/{keys,service,client,__main__}.py`, `config/tool_manifest.yaml`, `pyproject.toml`, `.gitattributes` | `pytest`: 111 passed (test_canonical, test_merkle, test_receipts, test_chain, test_measurement, test_notary_keys, test_notary_process) | Checkpoint 1 approved |
| 2026-11-23 | 1 | Tests: `tests/conftest.py` + 7 test modules. Golden vectors written by hand from RFC 8785; Merkle roots are the RFC 6962 / Certificate Transparency test data | Expected values come from the RFCs, not from the code under test | Checkpoint 1 approved |

| 2026-11-23 | 1 | Real notary key `a62a04bf20ca2931` created with `python -m mwia.notary keygen` (author-approved). Private key encrypted under `keys/private/` (owner-only ACL), public key + keyring under `keys/public/` | `icacls` output; `git status` shows only public files | Author approved Checkpoint 1 |
| 2026-11-23 | 2 | `src/mwia/common/fsperm.py` (shared ACL/hardening, refactored out of keys.py), `src/mwia/vault/{base,ledger,local,s3,anchor,__init__}.py`, `src/mwia/index/{db,provenance}.py`, `config/settings.yaml` | `pytest`: 183 passed + live DB test passed (MWIA_DB_TESTS=1); test_vault_local, test_vault_s3, test_anchor, test_index | Checkpoint 2 approved |
| 2026-11-23 | 2 | boto3 1.43.127 installed from `requirements-s3.txt`, only to check S3 parameter names against the botocore service model | Model introspection output | Checkpoint 2 approved |

| 2026-11-23 | 3 | `src/mwia/agent/{config,auth,http,policy_gate,transform,store,emit,m0_plan,m1_request,m2_response,m3_filter,m4_db,m5_complete,pipeline,__main__}.py`, `src/mwia/common/filelock.py`, `scripts/mwia.py`, `scripts/record_fixtures.py`, tool_manifest/settings updates | `pytest`: 230 passed (test_agent_units, test_pipeline + earlier suites); live runs below | Checkpoint 3 approved |
| 2026-11-23 | 3 | `tests/fixtures/observations_pool.json` (10 real observations, observer login/name/description redacted) | Golden row test: transform output equals the author's existing table row for 416484107 | Checkpoint 3 approved |
| 2026-11-23 | 3 | Live runs: dry run `--vault test --db prod` (942 fetched; 925 unchanged + 4 changed = the 929 existing rows; 13 new), real run `--vault test --db test` (942 inserted), immediate re-run (incremental window, 0 records), same-window re-run (942 unchanged) | Signatures verified with the committed public key; current `inaturalist_test` hash == PR4 readback hash; prod `inaturalist` still 929 rows | Checkpoint 3 approved |

| 2026-11-23 | 4 | `src/mwia/verify/{reader,findings,crypto,policy,evidence,engine,report,__main__}.py`, `templates/{run,index}.html.j2`, `config/verifier.yaml` (pins), pipeline integration (verdict, badge, provenance_index UPDATE, exit code) | `pytest`: 252 passed, incl. tests/test_verify.py with one case per eval scenario, an import-independence test, a read-only test and CLI exit codes | Checkpoint 4 approved |
| 2026-11-23 | 4 | Live demos (test env): green run (940 fetched, 1 updated), red bypass run with `place_id=1` (A=VERIFIED, B/C=FAILED at step 1), amber run with raw page 2 omitted before signing (A/B=VERIFIED, C=INSUFFICIENT) | Verdicts re-run with `verify --all`; verdicts recorded in provenance_index | Checkpoint 4 approved |

| 2026-11-23 | 5 | `eval/{harness,scenarios,metrics,run_eval}.py`, `tests/test_eval.py`; verifier changes: plan_deviation now localized to its first divergent step, an unsealed run that stopped part-way counts as incomplete rather than deviant (author's truncated = insufficient decision), and the decision-list fix below | `pytest`: 259 passed (test_eval smoke run of all 12 scenarios, hand-computed metric example, workdir guards; new regression test in test_verify) | Checkpoint 5 approved |
| 2026-11-23 | 5 | Full matrix: 12 scenarios × 30 repetitions × configs A/B/C, seed 20261123 → `eval/results/` (summary.md + CSVs). The first full run is archived in `eval/results/archive/run1-before-decision-list-fix/` | Measured numbers only; labels from the scenario generators | Checkpoint 5 approved |
| 2026-11-23 | 5 | Privacy fix: the fixture still held the observer's real numeric `user.id`; now pseudonymized (1001) in the fixture, the recorder script, the golden test and an eval variant label (also redacted in the archived run) | Recursive search: no real observer id or login in tests/, eval/, scripts/, src/, config/, docs/, templates/ | Checkpoint 5 approved |

| 2026-11-23 | 6 | `scripts/run_daily.ps1`, `scripts/run_daily.sh`, `scripts/register_task.ps1`, `scripts/launchd/org.masswildlife-integrity-agent.daily.plist`, `docs/SCHEDULING.md`, `tests/test_scheduling.py`, fixture attribution note (`tests/fixtures/README.md`) | `pytest`: 264 passed (parser checks for both scripts, plist parse). Manual runs against the test vault: PowerShell exit 0, Git Bash exit 0, lock held -> exit 4 propagated | Checkpoint 6 approved |
| 2026-11-23 | 6 | Pipeline fix: run state (the next window) is now written after verification, and a red or amber verdict doesn't count as covering the window | New assertion in `test_bypass_sends_unauthorized_request_but_scope_check_rejects`; eval regenerated with the changed code | Checkpoint 6 approved |

| 2026-11-23 | 7 | `README.md` (Mermaid architecture, setup, .env, token refresh, run/verify/eval, honest limits), `docs/VERIFICATION_METHODOLOGY.md` (threat model, trust assumptions, layers, decision rules, non-goals), `examples/` + `eval/make_examples.py` (synthetic runs only), `scripts/precommit_check.py` + `.githooks/pre-commit` (`core.hooksPath` set to `.githooks` in this clone), `tests/test_precommit.py`, `tests/test_hygiene.py` | `pytest`: 353 passed. `precommit_check.py --all`: 135 files that `git add -A` would add, clean (also checked against the real .env values in memory); search found no local username, machine name or email | pending (Checkpoint 7) |
| 2026-11-23 | 7 | First production run (author-approved), via `scripts/run_daily.ps1`: 940 fetched, 13 inserted, 5 updated, VERIFIED WITHIN SCOPE; created `vault/` and `anchors/` | Read-only check: `inaturalist` 942 rows, prod run state success, 7 provenance_index rows verified, one anchor commit | pending (Checkpoint 7) |

Phase 7 notes: the hygiene test found that the Phase 0 inspection script used non-standard header wording (fixed). Two `C:\Users\<name>` paths in docs/PROJECT_BRIEF.md Part B were replaced with `%USERPROFILE%`. Two tests built the PEM private-key header as a literal, and the new scanner flagged them; they now assemble it at runtime.

Phase 6 correction, found while exercising the scheduler script: the run state was written from the agent's own
status before verification, so a red run (the Checkpoint 4 bypass demo) counted as covering its window and moved
the next window forward. Fixed as above.

Phase 5 correction found by the evaluation (not by the unit tests): with PR3's decision list omitted, verifier
layer B reported every written record as "unaccepted", turning missing evidence into FAILED (8/30
omitted_evidence traces in run 1). Layer B now runs that check only when the decision list is present.
Regression test: `test_omitted_mandatory_evidence_is_insufficient_not_failed`. Run 1 is archived, and the
results were regenerated with the same seed.

Phase 4 corrections found by the tests: (1) the replay check only covered receipts on the reconstructed
chain, so an inserted foreign receipt was reported as a chain break but not as a replay. It now covers
every receipt under the run. (2) The HTTP client stamped `fetched_at` from the real clock while the tests
pinned the run clock, and the verifier correctly reported the responses as stale. The client now takes an
injectable wall clock.

Phase 3 corrections found by the tests: a missing data directory made the run lock fail on a fresh install
(`file_lock` now creates the parent); one window test had wrong expected arithmetic (the code was right).

Phase 1 corrections found by the tests: (1) on Windows, the private-key directory's ACL grant was not inheritable,
so new key files received the process's default DACL (SYSTEM + logon session). Fixed with `(OI)(CI)`. (2) Two test
assertions were wrong and were corrected: a Merkle "wrong size" negative that RFC 9162 legitimately accepts for
the same root, and an upper-case hex case that used an all-zero string.

## Library calls checked against the installed versions (Phase 1)
- `rfc8785.dumps(obj) -> bytes`; raises `IntegerDomainError` above 2^53 and `FloatDomainError` on NaN.
- `cryptography` 50.0.2: `Ed25519PrivateKey.generate()`, `private_bytes(PEM, PKCS8, BestAvailableEncryption(pw))`
  (gives `ENCRYPTED PRIVATE KEY`), `load_pem_private_key(data, password=)`, `public_bytes(Raw, Raw)` (32 bytes),
  `sign()` (64 bytes), `verify()` raises `InvalidSignature`.

## Library calls checked (Phase 2)
- botocore S3 model (boto3 1.43.127): `PutObject` has `IfNoneMatch`, `ObjectLockMode` (enum GOVERNANCE|COMPLIANCE),
  `ObjectLockRetainUntilDate`, `ChecksumSHA256` (Base64 SHA-256 digest). `PutObjectRetention(Retention={Mode, RetainUntilDate})`.
  `GetObjectRetention` returns `Retention`. `ListObjectsV2` has `Prefix`, `StartAfter`, `ContinuationToken` / `NextContinuationToken`, `IsTruncated`.
- Windows: `msvcrt.locking(fd, LK_NBLCK, 1)` for the vault lock; `icacls /deny user:(DE,WD,AD,WA,WEA)` on files,
  `(DE,DC)` on directories, verified by tests that `os.remove`, `open(..., "wb")`, `os.chmod` and `shutil.rmtree` fail.

## Facts checked (Phase 3)
- v2 OpenAPI: GET /observations security `userJwtOptional`, an apiKey in the `Authorization` header (raw JWT).
- PyMySQL 1.2.4 does not set `CLIENT.FOUND_ROWS` (checked on a live connection), so upsert affected rows are
  1 = insert, 2 = update, 0 = unchanged. MySQL server 8.0.27 supports `INSERT ... AS new ON DUPLICATE KEY UPDATE`.

## API facts verified against docs (not from model memory)
- `GET /v2/observations` params: `project_id`, `created_d1`, `created_d2`, `id_above`, `order_by` (enum includes `id`), `order` (`asc`/`desc`), `per_page`, `page`, `fields`.
- `fields` uses RISON-like syntax, e.g. `(id:!t,created_at:!t,user:(login:!t))`. Verified with a live request.
- Collection/umbrella membership is not in `project_ids`; `place_ids` contains 141552 for in-scope records (live probe, 942/942 on 2026-11-23).
- `created_d1` / `created_d2` accept ISO date-times (`Z` or offset), filter to the second, and are inclusive at both ends (live probe). `per_page=200` is accepted.
- The v2 `Observation` schema has no `positioning_method` / `positioning_device`. v2 timestamps carry the local offset; the table stores UTC.
