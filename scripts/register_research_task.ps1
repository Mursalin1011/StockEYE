# Registers the evening AI research review in Windows Task Scheduler for the current user (no admin needed).
#   Sun-Thu at 22:30, after the broker's daily market review usually arrives.
#   If the PC is off or asleep then, it runs as soon as possible afterwards (it doesn't wake the PC).
# Remove with:  Unregister-ScheduledTask -TaskName "StockEYE AI review" -Confirm:$false
param(
    [string]$TaskName = "StockEYE AI review",
    [string]$At = "22:30"
)
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "run_research.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday, Monday, Tuesday, Wednesday, Thursday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "StockEYE: AI review of new research PDFs to Telegram" -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
