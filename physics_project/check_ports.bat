@echo off
chcp 65001
title Port and Service Check

echo ========================================
echo   Port and Service Status Check
echo ========================================
echo.

echo [1/4] Checking port 80 (Nginx)...
netstat -ano | findstr ":80" | findstr "LISTENING"
if errorlevel 1 (
    echo ❌ Port 80 is not listening (Nginx not running)
) else (
    echo ✅ Port 80 is listening
)

echo [2/4] Checking port 5000 (Flask app)...
netstat -ano | findstr ":5000" | findstr "LISTENING"
if errorlevel 1 (
    echo ❌ Port 5000 is not listening (Flask app not running)
) else (
    echo ✅ Port 5000 is listening
)

echo [3/4] Checking Nginx process...
tasklist /fi "imagename eq nginx.exe"
if errorlevel 1 (
    echo ❌ No Nginx processes found
) else (
    echo ✅ Nginx processes found
)

echo [4/4] Checking Python processes...
tasklist /fi "imagename eq python.exe"
if errorlevel 1 (
    echo ❌ No Python processes found
) else (
    echo ✅ Python processes found
)

echo.
echo Testing application endpoints...
echo - Health check:
curl -s -o temp_health.txt -w "HTTP Status: %%{http_code}\n" http://localhost/health
if exist temp_health.txt (
    type temp_health.txt
    del temp_health.txt
)

echo - Main page:
curl -s -o temp_main.txt -w "HTTP Status: %%{http_code}\n" http://localhost/
if exist temp_main.txt (
    type temp_main.txt | findstr "DOCTYPE\|html" > nul && echo ✅ HTML response received || echo ❌ No HTML response
    del temp_main.txt
)

pause