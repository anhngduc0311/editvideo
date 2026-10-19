@echo off
chcp 65001 > nul
title Douyin Video AI Auto Editor - GUI Studio
cd /d "%~dp0"

echo ========================================================
echo   DOUYIN VIDEO AI AUTO-EDITOR - GRAPHICAL INTERFACE
echo ========================================================
echo.

set "PY_CMD="
where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY_CMD=python"
if not defined PY_CMD (
    where py >nul 2>nul && set "PY_CMD=py"
)
if not defined PY_CMD (
    if exist "C:\Program Files\Python313\python.exe" set "PY_CMD=C:\Program Files\Python313\python.exe"
)

if not defined PY_CMD (
    echo [ERROR] Khong tim thay Python! Vui long kiem tra lai cai dat Python.
    pause
    exit /b 1
)

"%PY_CMD%" app_gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Chuong trinh da ket thuc hoac co loi xay ra (Ma loi: %ERRORLEVEL%).
    pause
)

