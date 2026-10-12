# Runs the Telegram bot that answers /bought, /sold, /stop, /holdings, /undo (what Task Scheduler calls).
# Logs go to data/logs/bot-*.log. Stops when you log off; the scheduled task restarts it at logon.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
& "$root\.venv\Scripts\python.exe" -m dse_screener bot
exit $LASTEXITCODE
