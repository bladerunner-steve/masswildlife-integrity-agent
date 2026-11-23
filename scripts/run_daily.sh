#!/usr/bin/env bash
# run_daily.sh - the daily scheduled run on Linux/macOS (cron or launchd).
#
# It activates the venv, runs `agent run --vault prod --db prod`, then runs the independent verifier on the
# newest run (which also rewrites the badge and reports/index.html), and appends everything to
# logs/agent-YYYYMMDD.log (UTC date, the same date as the run's vault folder).
# Exit code: 0 only if the run succeeded unflagged AND the verdict is VERIFIED WITHIN SCOPE. It is non-zero
# for a red (2) or amber (1) result, for a flagged/partial/failed run, or if another run holds the lock (4).
# MWIA_VAULT / MWIA_DB default to prod. Set them to test only to try the script out.
# AI-assisted (Claude). Verified by: tests/test_scheduling.py (bash -n, defaults) and a manual run with
# MWIA_VAULT=test MWIA_DB=test (Checkpoint 6, via Git Bash).
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 3
VAULT="${MWIA_VAULT:-prod}"
DB="${MWIA_DB:-prod}"
case "$VAULT$DB" in prodprod|prodtest|testprod|testtest) ;; *) echo "MWIA_VAULT/MWIA_DB must be prod or test" >&2; exit 3;; esac

mkdir -p logs
LOG="logs/agent-$(date -u +%Y%m%d).log"
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

# POSIX venv layout, or the Windows layout when this script is run from Git Bash.
if [ -f .venv/bin/activate ]; then ACTIVATE=.venv/bin/activate; PY=.venv/bin/python
elif [ -f .venv/Scripts/activate ]; then ACTIVATE=.venv/Scripts/activate; PY=.venv/Scripts/python.exe
else log "ERROR: no .venv found (create the venv first)"; exit 3; fi
# shellcheck disable=SC1090
. "$ACTIVATE"
export PYTHONIOENCODING=utf-8

log "=== run_daily start (vault=$VAULT db=$DB)"
"$PY" scripts/mwia.py agent run --vault "$VAULT" --db "$DB" 2>&1 | sed 's/^/  /' >> "$LOG"
agent=${PIPESTATUS[0]}
log "agent run exit code $agent"
"$PY" scripts/mwia.py verify --vault "$VAULT" 2>&1 | sed 's/^/  /' >> "$LOG"
verify=${PIPESTATUS[0]}
log "verify exit code $verify (0 VERIFIED WITHIN SCOPE, 1 INSUFFICIENT EVIDENCE, 2 VERIFICATION FAILED, 3 input error)"

final=$(( agent > verify ? agent : verify ))
[ "$agent" -eq 4 ] && final=4   # another run was in progress: nothing new was verified
log "=== run_daily end, exit $final"
deactivate 2>/dev/null || true
exit "$final"
