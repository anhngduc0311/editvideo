@echo off
cd /d "%~dp0"
chcp 65001 > nul
title Douyin Video AI Auto Editor - GUI Studio
echo ========================================================
echo   DOUYIN VIDEO AI AUTO-EDITOR - GRAPHICAL INTERFACE
echo ========================================================
echo.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app_gui.py
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        python app_gui.py
    ) else (
        py -3 app_gui.py
    )
)
pause
