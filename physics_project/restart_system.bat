@echo off
chcp 65001
title Restart Exam System

echo ========================================
echo   Restarting Physics Exam System
echo ========================================
echo.

echo [1/5] Stopping all services...
taskkill /f /im nginx.exe > nul 2>&1
taskkill /f /im python.exe > nul 2>&1
timeout /t 2 > nul

echo [2/5] Activating virtual environment...
call venv\Scripts\activate.bat

echo [3/5] Starting Nginx...
cd /d D:\nginx
start nginx.exe
timeout /t 3 > nul

echo [4/5] Starting application server...
cd /d "%~dp0"
start "Exam System Server" python start_server.py

echo [5/5] Waiting for services to start...
timeout /t 5 > nul

echo.
echo Verifying services...
echo - Nginx status:
tasklist /fi "imagename eq nginx.exe" | find "nginx.exe" > nul && echo ✅ Running || echo ❌ Not running

echo - Application health:
curl -s http://localhost/health > nul && echo ✅ Healthy || echo ❌ Unhealthy

echo.
echo ========================================
echo   Restart completed!
echo   Access: http://localhost
echo ========================================
pause