@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" build_windows.py %*
) else (
    py -3 build_windows.py %*
)
if errorlevel 1 exit /b 1
