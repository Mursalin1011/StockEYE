# Registers the Telegram bot in Windows Task Scheduler for the current user (no admin needed).
#   Starts at logon and keeps running, so /bought and /sold get an answer within seconds.
#   If it stops (network loss, crash), Task Scheduler restarts it every 5 minutes, up to 999 times.
# Without it, the 3pm job still reads your messages, but Telegram drops unread ones after 24 hours.
# Remove with:  Unregister-ScheduledTask -TaskName "StockEYE bot" -Confirm:$false
param(
    [string]$TaskName = "StockEYE bot"
)
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "run_bot.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartInterval (New-TimeSpan -Minutes 5) -RestartCount 999 -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "StockEYE: answers your holdings commands in Telegram" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Select-Object TaskName, LastRunTime
