@echo off
chcp 65001 > nul
title AI Vocal Remover - Tach Giong Noi va Nhac Nen
echo ========================================================
echo   🎵 AI VOCAL REMOVER & KARAOKE CREATOR (MDX-NET)
echo ========================================================
echo Dang kiem tra va khoi dong giao dien...
echo.

cd /d "%~dp0"

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

"%PY_CMD%" main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Co loi xay ra khi chay chuong trinh.
    pause
)
