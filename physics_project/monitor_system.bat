@echo off
chcp 65001

REM 激活虚拟环境
call venv\Scripts\activate.bat

:loop
cls
echo ========================================
echo   考试系统实时监控（虚拟环境）
echo ========================================
echo 时间: %date% %time%
echo 虚拟环境: active
echo.

REM 检查 Nginx
tasklist /fi "imagename eq nginx.exe" | find "nginx.exe" > nul
if %errorlevel% == 0 (
    echo ✅ Nginx: 运行中
) else (
    echo ❌ Nginx: 未运行
)

REM 检查 Python (在虚拟环境中)
python -c "import sys; print(sys.prefix)" > nul 2>&1
if %errorlevel% == 0 (
    echo ✅ Python虚拟环境: 已激活
) else (
    echo ❌ Python虚拟环境: 未激活
)

REM 检查系统健康状态
curl -s http://localhost/health > temp_health.json
if %errorlevel% == 0 (
    echo ✅ 应用健康: 正常
) else (
    echo ❌ 应用健康: 异常
)

timeout /t 10 /nobreak > nul
goto loop