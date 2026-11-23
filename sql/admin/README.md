# Admin SQL scripts

These scripts create what the agent account `claude` (SELECT, INSERT and UPDATE on `masswildlife.*`) cannot
create itself. **The author runs them as a MySQL admin.** Each one is idempotent and starts with a header
comment explaining it. The agent never runs DDL.

## Run order

| # | Script | Creates / does | When |
|---|---|---|---|
| — | *(author's own rebuild of `inaturalist`, 2026-11-23)* | 40 columns, `PRIMARY KEY (id)` | done |
| 1 | `001_provenance_index.sql` | `provenance_index` (receipt index, untrusted convenience) | once, before Phase 2 |
| 2 | `002_run_state.sql` | `agent_run_state` (incremental windows) | once, before Phase 3 |
| 3 | `003_test_table.sql` | `inaturalist_test` (same structure as `inaturalist`) | once, before Phase 3 |
| 9 | `900_reset_test.sql` | **empties test data only** | whenever test/eval data should be reset |

`004_unique_obs_id.sql` is not needed: `inaturalist` already has `PRIMARY KEY (id)` (SHOW INDEX, 2026-11-23).

## Commands
Run these from the repo root. Replace `<admin>` with your admin user; MySQL prompts for the password.

PowerShell (Windows; PowerShell has no `<` input redirection, so use `source`):
```powershell
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u <admin> -p -e "source sql/admin/001_provenance_index.sql"
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u <admin> -p -e "source sql/admin/002_run_state.sql"
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u <admin> -p -e "source sql/admin/003_test_table.sql"
& "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe" -u <admin> -p -e "source sql/admin/900_reset_test.sql"
```

bash / cmd.exe:
```sh
mysql -u <admin> -p < sql/admin/001_provenance_index.sql
mysql -u <admin> -p < sql/admin/002_run_state.sql
mysql -u <admin> -p < sql/admin/003_test_table.sql
mysql -u <admin> -p < sql/admin/900_reset_test.sql
```

## Resetting the test vault (with 900_reset_test.sql)
The vault is write-once: its files are read-only, and on Windows they carry deny-delete ACEs. To reset the
**test** vault, deliberately lift that protection first, and remove the test anchors so they don't point
at runs that no longer exist. Never do this to `vault/` (production).

PowerShell:
```powershell
icacls vault-test /remove:d "$env:USERDOMAIN\$env:USERNAME" /T /C /Q
attrib -R vault-test\* /S /D
Remove-Item -Recurse -Force vault-test, anchors-test
```
bash: `chmod -R u+w vault-test && rm -rf vault-test anchors-test`

## Check afterwards (works as `claude`)
```sql
SHOW TABLES FROM masswildlife;
SHOW CREATE TABLE masswildlife.inaturalist_test;
```
