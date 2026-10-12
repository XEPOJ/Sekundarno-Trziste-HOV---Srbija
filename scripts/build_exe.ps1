$ErrorActionPreference = "Stop"
# Prefer the repo venv when present (local builds); CI has no venv and uses the PATH python.
$py = if (Test-Path .venv\Scripts\python.exe) { ".venv\Scripts\python.exe" } else { "python" }
if (-not (Test-Path data\seed.db)) {
    Write-Host "data\seed.db missing - building it from data\raw (run fetch-all first)"
    & $py -X utf8 -m securities_analyzer build-seed data\raw data\seed.db
    if ($LASTEXITCODE -ne 0) { throw "build-seed failed" }
}
& $py -m PyInstaller --noconfirm --clean --name SecuritiesAnalyzer --windowed `
    --add-data "securities_analyzer\ui;securities_analyzer\ui" `
    --add-data "data\seed.db;data" `
    --collect-submodules uvicorn --collect-all webview `
    run_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Write-Host "Built dist\SecuritiesAnalyzer\SecuritiesAnalyzer.exe"
