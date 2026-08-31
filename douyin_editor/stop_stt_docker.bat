@echo off
chcp 65001 >nul
echo [INFO] Đang dừng Docker Faster-Whisper STT Server...
docker compose -f docker-compose.stt.yml down
echo [INFO] Đã dừng Docker STT Server thành công!
pause
