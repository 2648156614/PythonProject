<#
.SYNOPSIS
    Best-effort Windows installer for local causal-conv1d / mamba-ssm source trees.

.DESCRIPTION
    SUMamba can run with the pure-PyTorch fallback in sumamba_windows/model.py.
    This script only attempts native extension installation when local source
    directories are present and the Windows build toolchain is available. If the
    prerequisites are missing, it exits successfully by default and leaves the
    fallback backend in use.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_mamba_from_local.ps1 -SourceRoot D:\ST\SUMamba

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_mamba_from_local.ps1 `
        -CausalConv1dPath D:\ST\SUMamba\causal-conv1d `
        -MambaSsmPath D:\ST\SUMamba\mamba-ssm `
        -Strict
#>

[CmdletBinding()]
param(
    [string]$SourceRoot = "D:\ST\SUMamba",
    [string]$CausalConv1dPath = "",
    [string]$MambaSsmPath = "",
    [switch]$Strict
)

$ErrorActionPreference = "Stop"

function Complete-Or-Skip {
    param([string]$Message)
    if ($Strict) {
        throw $Message
    }
    Write-Warning "$Message Native Mamba installation skipped; SUMamba will use the pure-PyTorch backend."
    exit 0
}

function Find-SourceDir {
    param(
        [string]$ExplicitPath,
        [string[]]$Candidates,
        [string]$PackageName
    )
    if ($ExplicitPath -and (Test-Path -LiteralPath $ExplicitPath)) {
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }
    foreach ($candidate in $Candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    Complete-Or-Skip "Could not find local source directory for $PackageName under $SourceRoot."
}

function Test-PythonPackage {
    param([string]$ModuleName)
    python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)" | Out-Null
    return ($LASTEXITCODE -eq 0)
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Complete-Or-Skip "Python was not found on PATH."
}

if (-not (Test-PythonPackage "torch")) {
    Complete-Or-Skip "PyTorch is not installed in the active Python environment. Install a Windows PyTorch build first."
}

$causalPath = Find-SourceDir `
    -ExplicitPath $CausalConv1dPath `
    -Candidates @(
        (Join-Path $SourceRoot "causal-conv1d"),
        (Join-Path $SourceRoot "causal_conv1d"),
        (Join-Path $SourceRoot "third_party\causal-conv1d")
    ) `
    -PackageName "causal-conv1d"

$mambaPath = Find-SourceDir `
    -ExplicitPath $MambaSsmPath `
    -Candidates @(
        (Join-Path $SourceRoot "mamba-ssm"),
        (Join-Path $SourceRoot "mamba_ssm"),
        (Join-Path $SourceRoot "third_party\mamba-ssm")
    ) `
    -PackageName "mamba-ssm"

Write-Host "Using causal-conv1d source: $causalPath"
Write-Host "Using mamba-ssm source:     $mambaPath"

if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    Write-Warning "cl.exe was not found. Open 'x64 Native Tools Command Prompt for VS' or run vcvars64.bat before this script."
}

if (-not (Get-Command nvcc.exe -ErrorAction SilentlyContinue)) {
    Write-Warning "nvcc.exe was not found. CUDA builds may fail unless the packages support CPU-only compilation in your local sources."
}

python -m pip install --upgrade pip setuptools wheel ninja packaging
if ($LASTEXITCODE -ne 0) { Complete-Or-Skip "Failed to install Python build helpers." }

Write-Host "Installing causal-conv1d from local source..."
python -m pip install --no-build-isolation -v $causalPath
if ($LASTEXITCODE -ne 0) { Complete-Or-Skip "causal-conv1d local build failed." }

Write-Host "Installing mamba-ssm from local source..."
python -m pip install --no-build-isolation -v $mambaPath
if ($LASTEXITCODE -ne 0) { Complete-Or-Skip "mamba-ssm local build failed." }

python -c "from mamba_ssm.modules.mamba_simple import Mamba; import causal_conv1d; print('native mamba backend is available')"
if ($LASTEXITCODE -ne 0) { Complete-Or-Skip "Installed packages could not be imported." }

Write-Host "Native mamba-ssm / causal-conv1d installation completed. You can set SUMAMBA_MAMBA_BACKEND=native or use mamba_backend='native'."
