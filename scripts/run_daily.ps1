<#
  run_daily.ps1 - the daily scheduled run on Windows (Task Scheduler).

  It activates the venv, runs `agent run --vault prod --db prod`, then runs the independent verifier on the
  newest run (which also rewrites the badge and reports/index.html), and appends everything to
  logs\agent-YYYYMMDD.log (UTC date, the same date as the run's vault folder).
  Exit code: 0 only if the run succeeded unflagged AND the verdict is VERIFIED WITHIN SCOPE. It is non-zero
  for a red (2) or amber (1) result, for a flagged/partial/failed run, or if another run holds the lock (4).
  -Vault / -Db default to prod. Pass test values only to try the script out.
  Secrets: nothing is printed except what the agent prints (it never prints the DB password or token).
  AI-assisted (Claude). Verified by: tests/test_scheduling.py (parse check, defaults) and a manual run with
  -Vault test -Db test (Checkpoint 6).
#>
param(
    [ValidateSet("prod", "test")] [string]$Vault = "prod",
    [ValidateSet("prod", "test")] [string]$Db = "prod"
)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("agent-{0}.log" -f (Get-Date).ToUniversalTime().ToString("yyyyMMdd"))

function Write-Log([string]$Message) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    Add-Content -LiteralPath $Log -Value "$stamp $Message" -Encoding UTF8
}

function Invoke-Logged([string[]]$Arguments) {
    # Native stderr lines become ErrorRecords in Windows PowerShell 5.1, so stop-on-error is turned off for
    # this call and each line is logged as text. The exit code comes from $LASTEXITCODE.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Python @Arguments 2>&1 | ForEach-Object { Add-Content -LiteralPath $Log -Value ("  " + $_.ToString()) -Encoding UTF8 }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    return $code
}

$Activate = Join-Path $Root ".venv\Scripts\Activate.ps1"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Log "ERROR: $Python not found (create the venv first)"
    exit 3
}
. $Activate
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Log "=== run_daily start (vault=$Vault db=$Db)"
$agentCode = Invoke-Logged @("scripts\mwia.py", "agent", "run", "--vault", $Vault, "--db", $Db)
Write-Log "agent run exit code $agentCode"
$verifyCode = Invoke-Logged @("scripts\mwia.py", "verify", "--vault", $Vault)
Write-Log "verify exit code $verifyCode (0 VERIFIED WITHIN SCOPE, 1 INSUFFICIENT EVIDENCE, 2 VERIFICATION FAILED, 3 input error)"

$final = [Math]::Max([int]$agentCode, [int]$verifyCode)
if ($agentCode -eq 4) { $final = 4 }   # another run was in progress: nothing new was verified
Write-Log "=== run_daily end, exit $final"
if (Get-Command deactivate -ErrorAction SilentlyContinue) { deactivate }
exit $final
