$ErrorActionPreference = 'Stop'
$readerPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $readerPython)) {
    throw 'Please set up the Python environment as described in README.txt first.'
}
& $readerPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt') 'pyinstaller>=6.15,<7'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location -LiteralPath $PSScriptRoot
try {
    & $readerPython -m PyInstaller --noconfirm --onefile --windowed --name YapBook --collect-all tkinterweb --collect-all tkinterweb_tkhtml --collect-all tkinterweb_tkhtml_extras --distpath (Join-Path $PSScriptRoot 'dist') --workpath (Join-Path $PSScriptRoot 'build') --specpath $PSScriptRoot (Join-Path $PSScriptRoot 'gui_entry.py')
    $readerBuildExit = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $readerBuildExit
