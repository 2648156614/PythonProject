"""Windows-friendly SUMamba reproduction package."""

from .model import SUMamba, SUMambaConfig, make_sumamba, native_mamba_available
from .preprocessing import fft_amplitude_phase, make_filter_bank_features
from .ssvep_dataset import (
    BenchmarkSSVEPDataset,
    benchmark_block_split,
    benchmark_channel_names,
    resolve_selected_channels,
)

__all__ = [
    "SUMamba",
    "SUMambaConfig",
    "make_sumamba",
    "native_mamba_available",
    "fft_amplitude_phase",
    "make_filter_bank_features",
    "BenchmarkSSVEPDataset",
    "benchmark_block_split",
    "benchmark_channel_names",
    "resolve_selected_channels",
]
