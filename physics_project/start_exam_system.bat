@echo off
chcp 65001 > nul
title Physics Exam System - Virtual Environment

echo ========================================
echo   Physics Exam System Startup
echo ========================================

REM Activate virtual environment
echo [1/4] Activating virtual environment...
call venv\Scripts\activate.bat

REM Check if virtual environment activated successfully
python -c "import sys; exit(0)" > nul 2>&1
if errorlevel 1 (
    echo ERROR: Virtual environment activation failed!
    echo Please check if exam_env exists.
    pause
    exit /b 1
)

REM Start Nginx
echo [2/4] Starting Nginx...
cd /d D:\nginx
start nginx.exe

REM Wait for Nginx to start
timeout /t 2 /nobreak > nul

REM Start Waitress server
echo [3/4] Starting Waitress server...
cd /d "%~dp0"
python start_server.py

echo [4/4] System started successfully!
echo Access URL: http://localhost
pause