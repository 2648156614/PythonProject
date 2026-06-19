"""Static checks for the Windows SUMamba reproduction."""

from pathlib import Path


def test_model_has_torch_fallback_and_optional_native_backend() -> None:
    source = Path("sumamba_windows/model.py").read_text(encoding="utf-8")
    assert "TorchMambaBlock" in source
    assert "mamba_backend" in source
    assert "native_mamba_available" in source
    assert "import mamba_ssm" not in source
    assert "import causal_conv1d" not in source
    assert "padding='same'" not in source


def test_package_exports_factory_and_backend_probe() -> None:
    source = Path("sumamba_windows/__init__.py").read_text(encoding="utf-8")
    assert "make_sumamba" in source
    assert "native_mamba_available" in source
    assert "fft_amplitude_phase" in source


def test_local_build_script_is_best_effort() -> None:
    source = Path("scripts/install_mamba_from_local.ps1").read_text(encoding="utf-8")
    assert 'D:\\ST\\SUMamba' in source
    assert "Complete-Or-Skip" in source
    assert "-Strict" in source


def test_windows_setup_bat_creates_venv_and_installs_dependencies() -> None:
    source = Path("scripts/setup_sumamba_windows.bat").read_text(encoding="utf-8")
    assert "-m venv" in source
    assert "pip install --upgrade torch" in source
    assert "requirements-windows.txt" in source
    assert "--native" in source
    assert "--cuda128" in source
    assert "--rtx5090" in source
    assert "setuptools<82" in source
    assert "--force-reinstall torch" in source
    assert "Activate.ps1" in source
    assert "Scripts\\python.exe" in source


def test_benchmark_dataset_and_training_script_are_available() -> None:
    dataset_source = Path("sumamba_windows/ssvep_dataset.py").read_text(encoding="utf-8")
    train_source = Path("sumamba_windows/train_benchmark.py").read_text(encoding="utf-8")
    init_source = Path("sumamba_windows/__init__.py").read_text(encoding="utf-8")

    assert "BenchmarkSSVEPDataset" in dataset_source
    assert "benchmark_block_split" in dataset_source
    assert "posterior30" in dataset_source
    assert "64-channels.loc" in dataset_source
    assert "resolve_selected_channels" in dataset_source
    assert "include_blocks" in dataset_source
    assert "exclude_blocks" in dataset_source
    assert "SUMambaConfig" in train_source
    assert "CosineAnnealingLR" in train_source
    assert "--data-root" in train_source
    assert "--print-channels" in train_source
    assert "BenchmarkSSVEPDataset" in init_source
    assert "resolve_selected_channels" in init_source
