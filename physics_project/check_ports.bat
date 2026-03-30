@echo off
chcp 65001
title Port and Service Check

echo ========================================
echo   Port and Service Status Check
echo ========================================
echo.

echo [1/7] Checking port 80 (Nginx)...
netstat -ano | findstr ":80" | findstr "LISTENING"
if errorlevel 1 (
    echo ❌ Port 80 is not listening (Nginx not running)
) else (
    echo ✅ Port 80 is listening
)

echo [2/7] Checking app ports (5000-5003)...
for %%P in (5000 5001 5002 5003) do (
    echo   - Checking port %%P...
    netstat -ano | findstr ":%%P" | findstr "LISTENING" > nul
    if errorlevel 1 (
        echo     ❌ Port %%P is not listening
    ) else (
        echo     ✅ Port %%P is listening
    )
)

echo [3/7] Checking Nginx process...
tasklist /fi "imagename eq nginx.exe"
if errorlevel 1 (
    echo ❌ No Nginx processes found
) else (
    echo ✅ Nginx processes found
)

echo [4/7] Checking Python processes...
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
