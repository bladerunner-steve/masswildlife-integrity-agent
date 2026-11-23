<#
  register_task.ps1 - create the daily Windows scheduled task "MassWildlife Integrity Agent" (run it yourself, once).

  It does what the GUI steps in docs/SCHEDULING.md describe: daily at -At (default 06:00 local time), runs
  scripts\run_daily.ps1 with powershell -NoProfile -ExecutionPolicy Bypass, and sets these task options:
    StartWhenAvailable  "Run task as soon as possible after a scheduled start is missed"
    MultipleInstances   IgnoreNew ("Do not start a new instance" if one is already running)
    ExecutionTimeLimit  2 hours; also allowed to start and keep running on battery
  It registers the task for the current user with "Run only when user is logged on". To switch it to "Run whether
  user is logged on or not", open Task Scheduler > the task > Properties > General and select that option.
  Windows then asks for your password and stores it; this script never handles your password.
  Re-running replaces the task (-Force).
  AI-assisted (Claude). Verified by: tests/test_scheduling.py (parse check). The author runs it; it was not
  run during development.
#>
param([string]$At = "06:00", [string]$TaskName = "MassWildlife Integrity Agent")

$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "scripts\run_daily.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`"" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Daily receipted iNaturalist ingest + integrity verification (masswildlife-integrity-agent)" -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, @{n = "Next run"; e = { ($_ | Get-ScheduledTaskInfo).NextRunTime } }
