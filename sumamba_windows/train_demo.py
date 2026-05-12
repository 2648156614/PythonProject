"""Minimal Windows-compatible training smoke demo for SUMamba.

Run after installing PyTorch:
    python -m sumamba_windows.train_demo
"""

from __future__ import annotations

import argparse

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .model import SUMambaConfig, SUMamba
from .preprocessing import fft_amplitude_phase


def build_demo_dataset(samples: int, eeg_channels: int, time_points: int, classes: int) -> TensorDataset:
    generator = torch.Generator().manual_seed(42)
    eeg = torch.randn(samples, eeg_channels, time_points, generator=generator)
    labels = torch.randint(0, classes, (samples,), generator=generator)
    features = fft_amplitude_phase(eeg, freq_bins=256)
    return TensorDataset(features, labels)


def main() -> None:
    parser = argparse.ArgumentParser(description="SUMamba Windows smoke-training demo")
    parser.add_argument("--classes", type=int, default=12)
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--mamba-backend", choices=["auto", "torch", "native"], default="torch")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dataset = build_demo_dataset(args.samples, args.channels, 512, args.classes)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)
    model = SUMamba(
        SUMambaConfig(
            num_classes=args.classes,
            num_eeg_channels=args.channels,
            freq_bins=256,
            spatial_depth=1,
            spatial_channels=4,
            mamba_backend=args.mamba_backend,
        )
    ).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    model.train()
    for epoch in range(args.epochs):
        running_loss = 0.0
        for features, labels in loader:
            features = features.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(features)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * features.shape[0]
        print(f"epoch={epoch + 1} loss={running_loss / len(dataset):.4f}")


if __name__ == "__main__":
    main()
