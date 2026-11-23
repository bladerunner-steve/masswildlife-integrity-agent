# Scheduling the daily run

The agent runs once every 24 hours. Each scheduled run:

1. activates `.venv`;
2. runs `agent run --vault prod --db prod`, which fetches, receipts, seals, anchors and verifies the run;
3. runs `verify --vault prod` on the newest run (and rewrites its badge and `reports/index.html`);
4. appends all output to `logs/agent-YYYYMMDD.log` (UTC date);
5. exits **non-zero on a red or amber result**, so the scheduler records the failure.

| Exit code | Meaning |
|---|---|
| 0 | run succeeded, nothing flagged, verdict VERIFIED WITHIN SCOPE |
| 1 | amber verdict (INSUFFICIENT EVIDENCE), or the run was partial or flagged (out-of-scope records, window gap, token needs refresh) |
| 2 | red verdict (VERIFICATION FAILED), or the run failed (for example, the policy gate blocked a request) |
| 3 | setup problem (no venv, no runs in the vault, bad arguments) |
| 4 | another run was still in progress, so this one did nothing |

Red and amber runs also add a line to `reports/ALERTS.md`.

## Windows: Task Scheduler

**One command (recommended).** From the repository root, in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_task.ps1          # daily at 06:00
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_task.ps1 -At 05:30
```

This creates the task **MassWildlife Integrity Agent** with "run as soon as possible after a missed start",
"do not start a new instance" and a 2-hour time limit. Then do step 5 of the GUI steps below ("Run whether user is
logged on or not"). Windows asks for your password at that point; the script never handles it.

**Equivalent `schtasks` command.** `schtasks` can't set the "missed start" option, so tick it afterwards in the GUI (step 7):

```bat
schtasks /Create /SC DAILY /ST 06:00 /TN "MassWildlife Integrity Agent" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\<you>\projects\masswildlife-integrity-agent\scripts\run_daily.ps1"
```

Adding `/RU <you> /RP` makes it run whether or not you are logged on (`/RP` with no value prompts for the password).

**GUI steps** (Task Scheduler → *Create Task…*, not *Create Basic Task*):

1. **General:** Name `MassWildlife Integrity Agent`.
2. **Triggers → New:** *Daily*, start 06:00, recur every 1 day.
3. **Actions → New:** *Start a program*. Program `powershell.exe`. Arguments
   `-NoProfile -ExecutionPolicy Bypass -File "C:\Users\<you>\projects\masswildlife-integrity-agent\scripts\run_daily.ps1"`.
   *Start in:* the repository folder.
4. **Conditions:** untick *Start the task only if the computer is on AC power* (laptops).
5. **General:** choose **Run whether user is logged on or not**. Leave *Do not store password* **unticked**: the
   task needs your account's access to the repository, keys and `.env`, and network access to iNaturalist.
6. **Settings:** **If the task is already running: Do not start a new instance**.
7. **Settings:** tick **Run task as soon as possible after a scheduled start is missed** (StartWhenAvailable).
8. **Settings:** *Stop the task if it runs longer than* 2 hours.

Check it with *Run* in Task Scheduler, or `schtasks /Run /TN "MassWildlife Integrity Agent"`, then look at
`logs\agent-YYYYMMDD.log` and `reports\index.html`. *Last Run Result* shows the exit code (0x1 amber, 0x2 red).

## Linux and macOS: cron

```cron
0 6 * * * cd /path/to/masswildlife-integrity-agent && ./scripts/run_daily.sh >> logs/cron.log 2>&1
```

Make the script executable once (`chmod +x scripts/run_daily.sh`). The detailed per-run log is still
`logs/agent-YYYYMMDD.log`. `logs/cron.log` only catches anything printed outside it.

**macOS:** cron may need *Full Disk Access* (System Settings → Privacy & Security → Full Disk Access → add
`/usr/sbin/cron`). The native alternative is launchd. Edit the paths in
`scripts/launchd/org.masswildlife-integrity-agent.daily.plist`, then:

```sh
cp scripts/launchd/org.masswildlife-integrity-agent.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/org.masswildlife-integrity-agent.daily.plist
```

launchd runs a job that was missed while the Mac slept as soon as it wakes.

## Missed days and late starts

The window logic handles them. It never silently widens a window:

- Each window starts 10 minutes before the previous successful window ended (the overlap catches records the API
  indexes late) and ends at the start of the current run. Re-reading the overlap is harmless because upserts are idempotent.
- A window is never longer than **24 h + 15 min grace** (`config/policy.yaml`). A run that starts up to about
  15 minutes late still covers everything.
- After a missed day (machine off, or the task skipped), the next run, started as soon as possible by the
  missed-start setting, covers the most recent 24 h 15 min. It **flags the uncovered gap** in seconds: PR0
  records `window.gap_seconds`, PR5 adds a `window_gap` flag, `reports/ALERTS.md` gets a line, and the exit code is 1.
- Backfilling the gap isn't automated. The windows always end "now", and widening one would break the 24-hour
  policy. If you need the missing records, ask for a bounded backfill option (for example, a `--window-end` flag;
  each backfill window would still have to fit the 24-hour limit).

## Before the first scheduled run

- Run it once by hand and check the log, the badge (`reports/runs/<run_id>/index.html`) and `reports/ALERTS.md`:
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_daily.ps1`
- The iNaturalist token is optional and expires after about 24 hours. With no valid token, runs read public data
  anonymously and the badge page shows a "token needs refresh" banner.
- To try the scripts without touching production, use the test vault and table:
  `scripts\run_daily.ps1 -Vault test -Db test`, or `MWIA_VAULT=test MWIA_DB=test ./scripts/run_daily.sh`.
