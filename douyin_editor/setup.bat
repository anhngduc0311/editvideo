@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" verify_setup.py
if errorlevel 1 exit /b 1
echo Setup completed. Start run_gui.bat to open the editor.
