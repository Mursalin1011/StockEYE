# Runs the evening AI research review (what Task Scheduler calls). Logs go to data/logs/research-*.log.
# Imports PDFs from data/inbox/pdf, scores matured AI calls, reviews new documents, sends to Telegram.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
& "$root\.venv\Scripts\python.exe" -m dse_screener research evening
exit $LASTEXITCODE
