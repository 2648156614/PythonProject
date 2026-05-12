@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM -----------------------------------------------------------------------------
REM Create a Windows virtual environment and install SUMamba Windows dependencies.
REM
REM Usage:
REM   scripts\setup_sumamba_windows.bat
REM   scripts\setup_sumamba_windows.bat --native
REM   scripts\setup_sumamba_windows.bat --cuda128
REM   scripts\setup_sumamba_windows.bat --rtx5090
REM   scripts\setup_sumamba_windows.bat --cuda126
REM   scripts\setup_sumamba_windows.bat --cuda118
REM
REM Optional environment variables:
REM   VENV_DIR        Virtual environment directory. Default: .venv
REM   PYTHON_EXE      Python launcher/executable. Default: py -3.11, then python
REM   TORCH_INDEX_URL PyTorch wheel index. Default: CPU wheels
REM   FORCE_REINSTALL_TORCH Set to 1 to replace an existing CPU/GPU torch wheel
REM   INSTALL_NATIVE  Set to 1 to try local mamba-ssm/causal-conv1d build
REM   SUMAMBA_SOURCE  Local source root for native build. Default: D:\ST\SUMamba
REM -----------------------------------------------------------------------------

set "ROOT_DIR=%~dp0.."
pushd "%ROOT_DIR%" >nul

set "VENV_DIR=%VENV_DIR%"
if "%VENV_DIR%"=="" set "VENV_DIR=.venv"

set "TORCH_INDEX_URL=%TORCH_INDEX_URL%"
set "INSTALL_NATIVE=%INSTALL_NATIVE%"
set "FORCE_REINSTALL_TORCH=%FORCE_REINSTALL_TORCH%"

:parse_args
if "%~1"=="" goto :after_args
if /I "%~1"=="--native" set "INSTALL_NATIVE=1"
if /I "%~1"=="/native" set "INSTALL_NATIVE=1"
if /I "%~1"=="--cpu" set "TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu"
if /I "%~1"=="--cuda118" set "TORCH_INDEX_URL=https://download.pytorch.org/whl/cu118"& set "FORCE_REINSTALL_TORCH=1"
if /I "%~1"=="--cuda126" set "TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126"& set "FORCE_REINSTALL_TORCH=1"
if /I "%~1"=="--cuda128" set "TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128"& set "FORCE_REINSTALL_TORCH=1"
if /I "%~1"=="--rtx5090" set "TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128"& set "FORCE_REINSTALL_TORCH=1"
shift
goto :parse_args

:after_args
if "%TORCH_INDEX_URL%"=="" set "TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu"
if "%FORCE_REINSTALL_TORCH%"=="" set "FORCE_REINSTALL_TORCH=0"

if not "%PYTHON_EXE%"=="" goto :python_ready
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PYTHON_EXE=py -3.11"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Python was not found. Install Python 3.10+ and add it to PATH.
        popd >nul
        exit /b 1
    )
    set "PYTHON_EXE=python"
)

:python_ready
echo [INFO] Project root: %CD%
echo [INFO] Python command: %PYTHON_EXE%
echo [INFO] Virtual environment: %VENV_DIR%
echo [INFO] PyTorch wheel index: %TORCH_INDEX_URL%

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [INFO] Creating virtual environment...
    %PYTHON_EXE% -m venv "%VENV_DIR%"
    if %ERRORLEVEL% NEQ 0 goto :fail
) else (
    echo [INFO] Reusing existing virtual environment.
)

call "%VENV_DIR%\Scripts\activate.bat"
if %ERRORLEVEL% NEQ 0 goto :fail

python -m pip install --upgrade pip wheel
if %ERRORLEVEL% NEQ 0 goto :fail

REM torch 2.11 CPU/CUDA wheels currently require setuptools<82. Do not upgrade
REM setuptools without a cap, otherwise pip prints a dependency conflict warning.
python -m pip install "setuptools<82"
if %ERRORLEVEL% NEQ 0 goto :fail

echo [INFO] Installing PyTorch from %TORCH_INDEX_URL%
if "%FORCE_REINSTALL_TORCH%"=="1" (
    echo [INFO] Reinstalling torch so the selected CPU/CUDA wheel replaces any existing torch build.
    python -m pip install --upgrade --force-reinstall torch --index-url "%TORCH_INDEX_URL%"
) else (
    python -m pip install --upgrade torch --index-url "%TORCH_INDEX_URL%"
)
if %ERRORLEVEL% NEQ 0 goto :fail

echo [INFO] Installing SUMamba Windows helper dependencies...
python -m pip install -r "sumamba_windows\requirements-windows.txt"
if %ERRORLEVEL% NEQ 0 goto :fail

python -c "import torch; from sumamba_windows import SUMambaConfig, native_mamba_available; print('torch', torch.__version__); print('native_mamba_available', native_mamba_available()); print('default_backend', SUMambaConfig().mamba_backend)"
if %ERRORLEVEL% NEQ 0 goto :fail

if "%INSTALL_NATIVE%"=="1" (
    set "SUMAMBA_SOURCE=%SUMAMBA_SOURCE%"
    if "!SUMAMBA_SOURCE!"=="" set "SUMAMBA_SOURCE=D:\ST\SUMamba"
    echo [INFO] Trying optional native mamba build from !SUMAMBA_SOURCE! ...
    powershell -ExecutionPolicy Bypass -File "scripts\install_mamba_from_local.ps1" -SourceRoot "!SUMAMBA_SOURCE!"
    if %ERRORLEVEL% NEQ 0 goto :fail
) else (
    echo [INFO] Skipping optional native mamba build. Re-run with --native or INSTALL_NATIVE=1 to try it.
)

echo.
echo [OK] SUMamba Windows environment is ready.
echo [OK] CMD activation: call "%VENV_DIR%\Scripts\activate.bat"
echo [OK] PowerShell activation: .\%VENV_DIR%\Scripts\Activate.ps1
echo [OK] Or run without activation: "%VENV_DIR%\Scripts\python.exe" -m sumamba_windows.train_demo --classes 12 --channels 8 --samples 16 --epochs 1 --mamba-backend torch
echo [OK] Smoke demo: python -m sumamba_windows.train_demo --classes 12 --channels 8 --samples 16 --epochs 1 --mamba-backend torch
echo [OK] CUDA check: python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
popd >nul
exit /b 0

:fail
echo.
echo [ERROR] Setup failed with exit code %ERRORLEVEL%.
echo [ERROR] Check the messages above. If native build failed, run without --native to use the pure-PyTorch backend.
popd >nul
exit /b 1
