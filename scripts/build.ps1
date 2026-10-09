$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = if ($env:POICOLLECTOR_PYTHON) {
    $env:POICOLLECTOR_PYTHON
} elseif (Test-Path -LiteralPath (Join-Path $projectRoot '.venv\Scripts\python.exe')) {
    (Join-Path $projectRoot '.venv\Scripts\python.exe')
} else {
    (Get-Command python -ErrorAction Stop).Source
}
$distPath = Join-Path $projectRoot 'output\package'
$workPath = Join-Path $projectRoot 'temp\pyinstaller'

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $distPath `
    --workpath $workPath `
    (Join-Path $projectRoot 'POICollector.spec')

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$exe = Join-Path $distPath 'POICollector_V2.0.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build output missing: $exe"
}

$item = Get-Item -LiteralPath $exe
[pscustomobject]@{
    Path = $item.FullName
    SizeMB = [math]::Round($item.Length / 1MB, 2)
    Under100MB = $item.Length -lt 100MB
}
