$ErrorActionPreference = 'Stop'
$readerPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $readerPython)) {
    throw 'Please set up the Python environment as described in README.txt first.'
}
& $readerPython -m pip install --require-hashes -r (Join-Path $PSScriptRoot 'quality\build.lock') --index-url https://pypi.org/simple
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location -LiteralPath $PSScriptRoot
try {
    & $readerPython -m PyInstaller --noconfirm --onefile --windowed --name YapBook --icon (Join-Path $PSScriptRoot 'assets\yapbook.ico') --add-data "assets;assets" --collect-all tkinterweb --collect-all tkinterweb_tkhtml --collect-all tkinterweb_tkhtml_extras --distpath (Join-Path $PSScriptRoot 'dist') --workpath (Join-Path $PSScriptRoot 'build') --specpath $PSScriptRoot (Join-Path $PSScriptRoot 'gui_entry.py')
    $readerBuildExit = $LASTEXITCODE
    if ($readerBuildExit -eq 0) {
        & $readerPython -c 'import sys; from app_branding import refresh_exe_icon; refresh_exe_icon(sys.argv[1])' (Join-Path $PSScriptRoot 'dist\YapBook.exe')
        if ($LASTEXITCODE -ne 0) { Write-Warning 'The EXE was built, but Explorer could not be notified to refresh its icon.' }
    }
}
finally {
    Pop-Location
}
exit $readerBuildExit
