$ErrorActionPreference = 'Stop'
$readerRoot = Split-Path -Parent $PSScriptRoot
$readerPython = Join-Path $readerRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $readerPython)) {
    throw 'Please set up the Python environment as described in README.md first.'
}
& $readerPython -m pip install --require-hashes -r (Join-Path $readerRoot 'requirements\requirements-build.txt') --index-url https://pypi.org/simple
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$readerAssetData = (Join-Path $readerRoot 'assets') + ';assets'
$readerWorkerData = (Join-Path $readerRoot 'yapbook\kokoro_worker.py') + ';yapbook'
$readerRuntimeData = (Join-Path $readerRoot 'requirements\requirements-kokoro.lock') + ';requirements'
Push-Location -LiteralPath $readerRoot
try {
    & $readerPython -m PyInstaller --noconfirm --onefile --windowed --name YapBook --paths $readerRoot --icon (Join-Path $readerRoot 'assets\yapbook.ico') --add-data $readerAssetData --add-data $readerWorkerData --add-data $readerRuntimeData --collect-all tkinterweb --collect-all tkinterweb_tkhtml --collect-all tkinterweb_tkhtml_extras --distpath (Join-Path $readerRoot 'dist') --workpath (Join-Path $readerRoot 'build') --specpath (Join-Path $readerRoot 'build') (Join-Path $PSScriptRoot 'launch_gui.py')
    $readerBuildExit = $LASTEXITCODE
    if ($readerBuildExit -eq 0) {
        & $readerPython -c 'import sys; from yapbook.app_branding import refresh_exe_icon; refresh_exe_icon(sys.argv[1])' (Join-Path $readerRoot 'dist\YapBook.exe')
        if ($LASTEXITCODE -ne 0) { Write-Warning 'The EXE was built, but Explorer could not be notified to refresh its icon.' }
    }
}
finally {
    Pop-Location
}
exit $readerBuildExit
