@echo off
chcp 65001 > nul
title AI Vocal Remover - Tach Giong Noi va Nhac Nen
echo ========================================================
echo   🎵 AI VOCAL REMOVER & KARAOKE CREATOR (MDX-NET)
echo ========================================================
echo Dang kiem tra va khoi dong giao dien...
echo.

python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Co loi xay ra khi chay chuong trinh.
    pause
)
