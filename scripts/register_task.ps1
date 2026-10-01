# Registers the daily job in Windows Task Scheduler for the current user (no admin needed).
#   Sun-Thu at 14:40; the job itself waits until 14:45 and retries until DSE publishes the data.
#   If the PC was off or asleep at 14:40, it runs as soon as possible afterwards.
# Remove with:  Unregister-ScheduledTask -TaskName "DSE Screener" -Confirm:$false
param(
    [string]$TaskName = "DSE Screener",
    [string]$At = "14:40"
)
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "run_daily.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday, Monday, Tuesday, Wednesday, Thursday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "DSE stock screener: daily summary to Telegram" -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
