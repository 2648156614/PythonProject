"""Train SUMamba on the Tsinghua Benchmark SSVEP dataset.

Example:
    python -m sumamba_windows.train_benchmark --data-root D:\\datasets\\Benchmark --subjects 1 --epochs 100
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from collections.abc import Iterable

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader

from .model import SUMamba, SUMambaConfig
from .ssvep_dataset import benchmark_block_split


def parse_int_list(value: str) -> list[int]:
    """Parse comma-separated integers and integer ranges such as ``1,2,5-7``."""

    output: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", maxsplit=1)
            output.extend(range(int(start), int(end) + 1))
        else:
            output.append(int(part))
    return output


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = True


def accuracy_from_logits(logits: torch.Tensor, labels: torch.Tensor) -> float:
    preds = logits.argmax(dim=1)
    return float((preds == labels).float().mean().item())


def run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    optimizer: torch.optim.Optimizer | None = None,
    use_amp: bool = False,
) -> tuple[float, float]:
    training = optimizer is not None
    model.train(training)
    total_loss = 0.0
    total_correct = 0
    total_count = 0
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp and training)

    for features, labels in loader:
        features = features.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        if training:
            optimizer.zero_grad(set_to_none=True)

        with torch.set_grad_enabled(training):
            with torch.amp.autocast("cuda", enabled=use_amp):
                logits = model(features)
                loss = criterion(logits, labels)

            if training:
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()

        batch_size = labels.shape[0]
        total_loss += float(loss.item()) * batch_size
        total_correct += int((logits.argmax(dim=1) == labels).sum().item())
        total_count += batch_size

    return total_loss / total_count, total_correct / total_count


def train_one_fold(args: argparse.Namespace, subject_id: int, test_block: int, device: torch.device) -> dict[str, float | int | str]:
    train_dataset, test_dataset = benchmark_block_split(
        root=args.data_root,
        subject_id=subject_id,
        test_block=test_block,
        selected_channels=args.channels,
        start_sample=args.start_sample,
        end_sample=args.end_sample,
        freq_bins=args.freq_bins,
        normalize_trials=not args.no_normalize,
        preload=not args.no_preload,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
    )
    test_loader = DataLoader(
        test_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
    )

    if args.print_channels:
        print(f"Using channels ({len(train_dataset.selected_channels)}): {train_dataset.selected_channel_names}")

    config = SUMambaConfig(
        num_classes=args.num_classes,
        num_eeg_channels=len(train_dataset.selected_channels),
        freq_bins=args.freq_bins,
        embed_dim=args.embed_dim,
        num_heads=args.num_heads,
        spatial_channels=args.spatial_channels,
        spatial_depth=args.spatial_depth,
        dropout=args.dropout,
        mamba_backend=args.mamba_backend,
    )
    model = SUMamba(config).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=args.min_lr)

    best_acc = 0.0
    best_epoch = 0
    best_path = Path(args.output_dir) / f"subject{subject_id:02d}_block{test_block + 1}_best.pt"
    use_amp = args.amp and device.type == "cuda"

    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = run_epoch(model, train_loader, criterion, device, optimizer, use_amp=use_amp)
        test_loss, test_acc = run_epoch(model, test_loader, criterion, device, optimizer=None, use_amp=use_amp)
        scheduler.step()

        if test_acc > best_acc:
            best_acc = test_acc
            best_epoch = epoch
            if args.save_checkpoints:
                torch.save(
                    {
                        "model_state_dict": model.state_dict(),
                        "config": config,
                        "subject_id": subject_id,
                        "test_block": test_block,
                        "epoch": epoch,
                        "test_acc": test_acc,
                    },
                    best_path,
                )

        if epoch == 1 or epoch % args.log_interval == 0 or epoch == args.epochs:
            print(
                f"subject={subject_id:02d} fold={test_block + 1}/6 epoch={epoch:03d} "
                f"train_loss={train_loss:.4f} train_acc={train_acc:.4f} "
                f"test_loss={test_loss:.4f} test_acc={test_acc:.4f} best={best_acc:.4f}"
            )

    return {
        "subject_id": subject_id,
        "test_block": test_block + 1,
        "best_epoch": best_epoch,
        "best_acc": best_acc,
        "checkpoint": str(best_path) if args.save_checkpoints else "",
    }


def write_results(results: Iterable[dict[str, float | int | str]], output_dir: str | Path) -> None:
    output_path = Path(output_dir) / "benchmark_results.csv"
    rows = list(results)
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=["subject_id", "test_block", "best_epoch", "best_acc", "checkpoint"])
        writer.writeheader()
        writer.writerows(rows)
    mean_acc = float(np.mean([float(row["best_acc"]) for row in rows]))
    print(f"Saved fold results to {output_path}")
    print(f"Mean best accuracy across {len(rows)} folds: {mean_acc:.4f}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train SUMamba on the Tsinghua Benchmark SSVEP dataset")
    parser.add_argument("--data-root", required=True, help="Directory containing S1.mat ... S35.mat")
    parser.add_argument("--output-dir", default="outputs/benchmark_sumamba")
    parser.add_argument("--subjects", default="1-35", help="Subjects, e.g. 1, 1-5, or 1,3,7")
    parser.add_argument("--folds", default="0-5", help="Zero-based held-out Benchmark block IDs")
    parser.add_argument(
        "--channels",
        default="posterior30",
        help="Channel preset/name/index spec: posterior30 (default), occipital, parieto_occipital, first30, POZ,OZ,O1,O2, or 52-62",
    )
    parser.add_argument("--start-sample", type=int, default=125)
    parser.add_argument("--end-sample", type=int, default=625)
    parser.add_argument("--freq-bins", type=int, default=256)
    parser.add_argument("--num-classes", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--min-lr", type=float, default=1e-6)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--embed-dim", type=int, default=256)
    parser.add_argument("--num-heads", type=int, default=2)
    parser.add_argument("--spatial-channels", type=int, default=4)
    parser.add_argument("--spatial-depth", type=int, default=6)
    parser.add_argument("--dropout", type=float, default=0.4)
    parser.add_argument("--mamba-backend", choices=["auto", "torch", "native"], default="torch")
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--amp", action="store_true", help="Use CUDA automatic mixed precision")
    parser.add_argument("--save-checkpoints", action="store_true")
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--no-preload", action="store_true")
    parser.add_argument("--log-interval", type=int, default=10)
    parser.add_argument("--print-channels", action="store_true", help="Print resolved channel names for each fold")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    set_seed(args.seed)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device={device}; torch={torch.__version__}; cuda_available={torch.cuda.is_available()}")
    if device.type == "cuda":
        print(f"CUDA device: {torch.cuda.get_device_name(0)}")

    subjects = parse_int_list(args.subjects)
    folds = parse_int_list(args.folds)
    results = []
    for subject_id in subjects:
        for test_block in folds:
            results.append(train_one_fold(args, subject_id, test_block, device))
    write_results(results, args.output_dir)


if __name__ == "__main__":
    main()
