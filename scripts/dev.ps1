# Starts the StockEYE API and web dashboard for local use (this PC only).
#   API:       http://127.0.0.1:8000/api/docs
#   Dashboard: http://127.0.0.1:3000
# Close both windows (or Ctrl+C) to stop.
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; .\.venv\Scripts\python.exe -m dse_screener api"
Set-Location "$root\web"
if (-not (Test-Path node_modules)) { npm install }
npm run dev
