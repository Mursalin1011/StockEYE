# Runs the daily screener job (what Task Scheduler calls). Logs go to data/logs/.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
& "$root\.venv\Scripts\python.exe" -m dse_screener daily
exit $LASTEXITCODE
