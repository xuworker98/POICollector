$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = if ($env:POICOLLECTOR_PYTHON) {
    $env:POICOLLECTOR_PYTHON
} elseif (Test-Path -LiteralPath (Join-Path $ProjectRoot '.venv\Scripts\python.exe')) {
    (Join-Path $ProjectRoot '.venv\Scripts\python.exe')
} else {
    (Get-Command python -ErrorAction Stop).Source
}
$env:QT_QPA_PLATFORM = 'offscreen'
Set-Location -LiteralPath $ProjectRoot
& $Python -m pytest -q
