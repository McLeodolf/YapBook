@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0read_epub.py" --follow %*
if errorlevel 1 pause
