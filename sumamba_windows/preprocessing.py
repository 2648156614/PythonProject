"""Preprocessing helpers for SUMamba SSVEP experiments."""

from __future__ import annotations

from collections.abc import Iterable

import torch
from torch import Tensor


def fft_amplitude_phase(eeg: Tensor, n_fft: int | None = None, freq_bins: int = 256) -> Tensor:
    """Convert time-domain EEG into SUMamba amplitude/phase features.

    Args:
        eeg: Tensor shaped ``[batch, eeg_channels, samples]``.
        n_fft: Optional FFT length.  Defaults to the sample length.
        freq_bins: Number of positive-frequency bins kept for the model.

    Returns:
        Tensor shaped ``[batch, 2, eeg_channels, freq_bins]`` where channel 0 is
        normalized amplitude and channel 1 is phase in radians.
    """

    if eeg.ndim != 3:
        raise ValueError("eeg must be shaped [batch, eeg_channels, samples]")
    fft = torch.fft.rfft(eeg, n=n_fft or eeg.shape[-1], dim=-1)
    if fft.shape[-1] < freq_bins:
        pad = freq_bins - fft.shape[-1]
        fft = torch.nn.functional.pad(fft, (0, pad))
    fft = fft[..., :freq_bins]
    amplitude = torch.abs(fft)
    amplitude = amplitude / amplitude.amax(dim=-1, keepdim=True).clamp_min(1e-6)
    phase = torch.angle(fft)
    return torch.stack([amplitude, phase], dim=1)


def make_filter_bank_features(
    eeg_bands: Iterable[Tensor], n_fft: int | None = None, freq_bins: int = 256
) -> Tensor:
    """Build FB-SUMamba style features from pre-filtered EEG bands.

    The original paper extends SUMamba with a filter-bank front end.  This
    helper expects each band to be already filtered by the caller, converts every
    band to amplitude/phase features, and stacks them as
    ``[batch, bands, 2, eeg_channels, freq_bins]`` for band-wise ensembling or a
    custom FB-SUMamba training loop.
    """

    features = [fft_amplitude_phase(band, n_fft=n_fft, freq_bins=freq_bins) for band in eeg_bands]
    if not features:
        raise ValueError("eeg_bands must contain at least one tensor")
    return torch.stack(features, dim=1)
