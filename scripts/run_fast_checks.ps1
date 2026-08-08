$ErrorActionPreference = "Stop"

$Python = "D:\anaconda\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project Python was not found: $Python"
}

& $Python -m compileall -q core scripts tests
if ($LASTEXITCODE -ne 0) {
    throw "compileall failed with exit code $LASTEXITCODE"
}

& $Python scripts\run_production_tests.py
if ($LASTEXITCODE -ne 0) {
    throw "production test suite failed with exit code $LASTEXITCODE"
}
