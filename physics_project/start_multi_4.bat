@echo off
chcp 65001 >nul
title 启动物理考试系统 - 4 实例

echo =========================================
echo 启动 Waitress 4 实例（5000-5003）
echo =========================================

REM 启动 5000（主实例，建议第一个启动）
start "Waitress :5000" cmd /k ^
"set PORT=5000 && python start_server.py"

timeout /t 2 >nul

REM 启动 5001
start "Waitress :5001" cmd /k ^
"set PORT=5001 && python start_server.py"

timeout /t 2 >nul

REM 启动 5002
start "Waitress :5002" cmd /k ^
"set PORT=5002 && python start_server.py"

timeout /t 2 >nul

REM 启动 5003
start "Waitress :5003" cmd /k ^
"set PORT=5003 && python start_server.py"

echo =========================================
echo 所有实例已启动
echo 请不要关闭这些窗口
echo =========================================
