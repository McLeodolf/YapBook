@echo off
setlocal
pushd "%~dp0" || exit /b 1
"%~dp0.venv\Scripts\python.exe" -m yapbook.read_epub --follow %*
set "readerExitCode=%errorlevel%"
popd
if not "%readerExitCode%"=="0" pause
exit /b %readerExitCode%
