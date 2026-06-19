"""Dataset utilities for the Tsinghua Benchmark SSVEP dataset.

Expected MATLAB layout per subject: ``data`` with shape
``[64, 1500, 40, 6]`` = channels, samples, targets, blocks/trials.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable

import numpy as np
import scipy.io as sio
import torch
from torch import Tensor
from torch.utils.data import Dataset

from .preprocessing import fft_amplitude_phase

BENCHMARK_64_CHANNELS = [
    "FP1", "FPZ", "FP2", "AF3", "AF4", "F7", "F5", "F3",
    "F1", "FZ", "F2", "F4", "F6", "F8", "FT7", "FC5",
    "FC3", "FC1", "FCZ", "FC2", "FC4", "FC6", "FT8", "T7",
    "C5", "C3", "C1", "CZ", "C2", "C4", "C6", "T8",
    "M1", "TP7", "CP5", "CP3", "CP1", "CPZ", "CP2", "CP4",
    "CP6", "TP8", "M2", "P7", "P5", "P3", "P1", "PZ",
    "P2", "P4", "P6", "P8", "PO7", "PO5", "PO3", "POZ",
    "PO4", "PO6", "PO8", "CB1", "O1", "OZ", "O2", "CB2",
]

CHANNEL_PRESETS = {
    # The original Windows reproduction accidentally used the first 30 channels,
    # which are mostly frontal/central.  For SSVEP, prefer posterior channels.
    "first30": list(range(30)),
    "posterior30": list(range(34, 64)),  # CP5..CB2, 30 channels
    "parieto_occipital": list(range(43, 63)),  # P7..O2, 20 channels
    "occipital": [52, 53, 54, 55, 56, 57, 58, 60, 61, 62],  # PO/O channels
    "sumamba30": list(range(34, 64)),
}


@dataclass(frozen=True)
class BenchmarkTrialIndex:
    """Identifies one Benchmark trial."""

    subject_id: int
    class_id: int
    block_id: int


def _normalize_channel_name(name: str) -> str:
    return name.strip().upper().replace(" ", "")


def load_loc_channel_names(loc_path: str | Path) -> list[str]:
    """Read channel labels from an EEGLAB-style ``.loc``/``.locs`` file.

    Benchmark's ``64-channels.loc`` is commonly stored as numeric columns plus
    the channel label.  This parser takes the last token from each non-empty
    non-comment line, which is robust for the usual ``index theta radius label``
    format.
    """

    names: list[str] = []
    with Path(loc_path).open("r", encoding="utf-8-sig") as fp:
        for line in fp:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("%"):
                continue
            names.append(_normalize_channel_name(stripped.split()[-1]))
    if not names:
        raise ValueError(f"No channel names found in {loc_path}")
    return names


def benchmark_channel_names(root: str | Path) -> list[str]:
    """Return Benchmark channel names from ``64-channels.loc`` if present."""

    root_path = Path(root)
    for file_name in ("64-channels.loc", "64-channels.locs"):
        loc_path = root_path / file_name
        if loc_path.exists():
            return load_loc_channel_names(loc_path)
    return BENCHMARK_64_CHANNELS


def parse_channel_spec(spec: str) -> list[int] | list[str]:
    """Parse channel specs such as ``posterior30``, ``41-63`` or ``POZ,OZ``."""

    normalized = spec.strip()
    preset_key = normalized.lower().replace("-", "_")
    if preset_key in CHANNEL_PRESETS:
        return CHANNEL_PRESETS[preset_key]

    items = [item.strip() for item in normalized.split(",") if item.strip()]
    if not items:
        raise ValueError("channel specification is empty")

    if all(item.replace("-", "", 1).isdigit() or ("-" in item and item.replace("-", "").isdigit()) for item in items):
        indices: list[int] = []
        for item in items:
            if "-" in item:
                start, end = item.split("-", maxsplit=1)
                indices.extend(range(int(start), int(end) + 1))
            else:
                indices.append(int(item))
        return indices

    names: list[str] = []
    for item in items:
        key = item.lower().replace("-", "_")
        if key in CHANNEL_PRESETS:
            names.extend(BENCHMARK_64_CHANNELS[index] for index in CHANNEL_PRESETS[key])
        else:
            names.append(item)
    return names


def resolve_selected_channels(
    selected_channels: str | Iterable[int] | Iterable[str] | None,
    root: str | Path | None = None,
) -> list[int]:
    """Resolve channel indices from a preset, numeric list, or channel names."""

    if selected_channels is None:
        selected_channels = "posterior30"
    if isinstance(selected_channels, str):
        selected_channels = parse_channel_spec(selected_channels)

    values = list(selected_channels)
    if not values:
        raise ValueError("selected_channels must not be empty")
    if all(isinstance(value, int) for value in values):
        return [int(value) for value in values]

    names = benchmark_channel_names(root or ".")
    name_to_index = {_normalize_channel_name(name): index for index, name in enumerate(names)}
    indices: list[int] = []
    for value in values:
        key = _normalize_channel_name(str(value))
        if key not in name_to_index:
            available = ",".join(names)
            raise ValueError(f"Unknown channel name {value!r}. Available channels: {available}")
        indices.append(name_to_index[key])
    return indices


class BenchmarkSSVEPDataset(Dataset[tuple[Tensor, Tensor]]):
    """PyTorch dataset for subject/block splits on Benchmark SSVEP.

    The class intentionally keeps split logic explicit.  For a strict
    subject-dependent Benchmark protocol, create six folds by passing one
    ``test_block`` at a time and use the other five blocks for training.

    Args:
        root: Directory containing ``S1.mat`` ... ``S35.mat``.
        subject_ids: Subject numbers to load.  Defaults to all 35 subjects.
        selected_channels: Channel preset/name/index spec.  Defaults to
            ``posterior30`` (CP5..CB2), because SSVEP is strongest over
            parietal/occipital areas.  Other presets: ``first30``,
            ``parieto_occipital``, ``occipital``.  You may also pass names such
            as ``POZ,OZ,O1,O2`` or zero-based numeric ranges such as ``52-62``.
        start_sample: Inclusive sample index for the analysis window.
        end_sample: Exclusive sample index for the analysis window.
        freq_bins: Number of FFT bins supplied to SUMamba.
        include_blocks: Optional block/trial IDs to include, zero-based.
        exclude_blocks: Optional block/trial IDs to skip, zero-based.
        normalize_trials: If true, z-score each trial per channel before FFT.
        preload: If true, compute all FFT features in ``__init__``.  If false,
            keep time-domain trials and compute features in ``__getitem__``.
    """

    def __init__(
        self,
        root: str | Path,
        subject_ids: Iterable[int] | None = None,
        selected_channels: str | Iterable[int] | Iterable[str] | None = None,
        start_sample: int = 125,
        end_sample: int = 625,
        freq_bins: int = 256,
        include_blocks: Iterable[int] | None = None,
        exclude_blocks: Iterable[int] | None = None,
        normalize_trials: bool = True,
        preload: bool = True,
    ) -> None:
        self.root = Path(root)
        self.freq_bins = freq_bins
        self.normalize_trials = normalize_trials
        self.preload = preload

        if subject_ids is None:
            subject_ids = range(1, 36)

        self.subject_ids = list(subject_ids)
        self.channel_names = benchmark_channel_names(self.root)
        self.selected_channels = resolve_selected_channels(selected_channels, self.root)
        self.selected_channel_names = [self.channel_names[index] for index in self.selected_channels]
        self.include_blocks = None if include_blocks is None else set(include_blocks)
        self.exclude_blocks = set() if exclude_blocks is None else set(exclude_blocks)
        self.trial_index: list[BenchmarkTrialIndex] = []

        if start_sample < 0 or end_sample <= start_sample:
            raise ValueError("end_sample must be greater than start_sample")
        if not self.root.exists():
            raise FileNotFoundError(f"Benchmark root does not exist: {self.root}")

        all_x: list[np.ndarray] = []
        all_y: list[int] = []

        for subject_id in self.subject_ids:
            mat_path = self.root / f"S{subject_id}.mat"
            if not mat_path.exists():
                raise FileNotFoundError(f"Missing Benchmark subject file: {mat_path}")
            mat = sio.loadmat(mat_path)
            if "data" not in mat:
                raise KeyError(f"{mat_path} does not contain a 'data' array")

            data = mat["data"]
            if data.ndim != 4:
                raise ValueError(f"Expected [channels, samples, classes, blocks], got {data.shape}")
            if max(self.selected_channels) >= data.shape[0] or min(self.selected_channels) < 0:
                raise ValueError(f"selected_channels are out of range for {mat_path}: {data.shape[0]} channels")
            if end_sample > data.shape[1]:
                raise ValueError(f"Requested end_sample={end_sample}, but {mat_path} has {data.shape[1]} samples")

            data = data[self.selected_channels, start_sample:end_sample, :, :]
            _channels, _time_points, num_classes, num_blocks = data.shape

            for class_id in range(num_classes):
                for block_id in range(num_blocks):
                    if self.include_blocks is not None and block_id not in self.include_blocks:
                        continue
                    if block_id in self.exclude_blocks:
                        continue
                    trial = np.asarray(data[:, :, class_id, block_id], dtype=np.float32)
                    all_x.append(trial)
                    all_y.append(class_id)
                    self.trial_index.append(BenchmarkTrialIndex(subject_id, class_id, block_id))

        if not all_x:
            raise ValueError("No Benchmark trials were selected; check subject/block filters")

        x = torch.tensor(np.stack(all_x, axis=0), dtype=torch.float32)
        self.labels = torch.tensor(np.asarray(all_y, dtype=np.int64), dtype=torch.long)
        self.time_trials = self._normalize(x) if normalize_trials else x
        self.features = fft_amplitude_phase(self.time_trials, freq_bins=freq_bins) if preload else None

    @staticmethod
    def _normalize(x: Tensor) -> Tensor:
        mean = x.mean(dim=-1, keepdim=True)
        std = x.std(dim=-1, keepdim=True).clamp_min(1e-6)
        return (x - mean) / std

    def __len__(self) -> int:
        return int(self.labels.numel())

    def __getitem__(self, index: int) -> tuple[Tensor, Tensor]:
        if self.features is not None:
            return self.features[index], self.labels[index]
        feature = fft_amplitude_phase(self.time_trials[index].unsqueeze(0), freq_bins=self.freq_bins).squeeze(0)
        return feature, self.labels[index]


def benchmark_block_split(
    root: str | Path,
    subject_id: int,
    test_block: int,
    selected_channels: str | Iterable[int] | Iterable[str] | None = None,
    start_sample: int = 125,
    end_sample: int = 625,
    freq_bins: int = 256,
    normalize_trials: bool = True,
    preload: bool = True,
) -> tuple[BenchmarkSSVEPDataset, BenchmarkSSVEPDataset]:
    """Create one subject-dependent Benchmark fold.

    ``test_block`` is zero-based.  The training split uses the remaining five
    blocks; the test split uses exactly ``test_block``.
    """

    train_dataset = BenchmarkSSVEPDataset(
        root=root,
        subject_ids=[subject_id],
        selected_channels=selected_channels,
        start_sample=start_sample,
        end_sample=end_sample,
        freq_bins=freq_bins,
        exclude_blocks=[test_block],
        normalize_trials=normalize_trials,
        preload=preload,
    )
    test_dataset = BenchmarkSSVEPDataset(
        root=root,
        subject_ids=[subject_id],
        selected_channels=selected_channels,
        start_sample=start_sample,
        end_sample=end_sample,
        freq_bins=freq_bins,
        include_blocks=[test_block],
        normalize_trials=normalize_trials,
        preload=preload,
    )
    return train_dataset, test_dataset
