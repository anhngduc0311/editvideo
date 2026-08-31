@echo off
chcp 65001 >nul
echo [INFO] Đang khởi động Docker Faster-Whisper STT Server trên cổng 8888...
docker compose -f docker-compose.stt.yml up -d
echo [INFO] Docker STT Server đã chạy ở chế độ nền! (Endpoint: http://localhost:8888)
pause
