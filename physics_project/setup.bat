@echo off
chcp 65001 > nul
echo ========================================
echo   物理考试系统环境配置（虚拟环境）
echo ========================================
echo.

echo [1/4] 激活虚拟环境...
call venv\Scripts\activate.bat

echo [2/4] 检查 Python 环境...
python --version

echo [3/4] 修复并安装依赖...
del requirements.txt 2>nul
(
echo Flask==2.3.3
echo Werkzeug==2.3.7
echo mysql-connector-python==8.1.0
echo sympy==1.12
echo waitress==2.1.2
echo Jinja2==3.1.2
) > requirements.txt

pip install -r requirements.txt

echo [4/4] 验证安装...
python -c "import flask; print('FLASK: OK')"
python -c "import mysql.connector; print('MYSQL: OK')"
python -c "import sympy; print('SYMPY: OK')"
python -c "import waitress; print('WAITRESS: OK')"

echo.
echo ========================================
echo   环境配置完成!
echo ========================================
pause