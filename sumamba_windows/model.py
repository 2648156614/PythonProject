"""Windows-friendly reproduction of the SUMamba model for SSVEP classification.

The original SUMamba repository depends on ``mamba-ssm`` and ``causal-conv1d``,
which compile custom CUDA/C++ kernels and are difficult to install on Windows.
This module keeps the paper/code structure: FFT amplitude/phase input,
spatial-attention feature enhancement, U-Net style multi-scale fusion, parallel
Mamba-like sequence heads, channel attention, and an MLP classifier.  The Mamba
block below defaults to ordinary PyTorch operators so it runs on Windows CPU/CUDA
builds without Linux-only extensions; an optional native backend can use a locally
compiled mamba-ssm installation.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import torch
from torch import Tensor, nn
import torch.nn.functional as F


@dataclass(frozen=True)
class SUMambaConfig:
    """Configuration matching the dimensions used by the SUMamba paper code.

    Attributes:
        num_classes: Number of SSVEP stimulus classes.
        num_eeg_channels: Number of EEG channels after channel selection.
        freq_bins: Number of FFT bins used as model features.
        embed_dim: Frequency feature width after the final U-Net down/up path.
        num_heads: Number of parallel Mamba-like heads.
        spatial_channels: Channels produced by the spatial feature enhancer.
        spatial_depth: Number of spatial-attention encoder blocks.
        spatial_kernel_size: 2-D kernel used by spatial attention.
        dropout: Dropout probability used in fusion/classifier layers.
        mamba_backend: ``"auto"`` uses a compiled local ``mamba-ssm`` install when
            available and otherwise falls back to pure PyTorch; ``"torch"`` always
            uses the portable fallback; ``"native"`` requires compiled mamba-ssm.
    """

    num_classes: int = 40
    num_eeg_channels: int = 30
    freq_bins: int = 256
    embed_dim: int = 256
    num_heads: int = 2
    spatial_channels: int = 4
    spatial_depth: int = 6
    spatial_kernel_size: tuple[int, int] = (7, 7)
    dropout: float = 0.4
    mamba_backend: str = "auto"

    def validate(self) -> None:
        if self.freq_bins % 8 != 0:
            raise ValueError("freq_bins must be divisible by 8 for the 3-level U-Net path")
        if self.embed_dim % self.num_heads != 0:
            raise ValueError("embed_dim must be divisible by num_heads")
        if self.num_eeg_channels < 1:
            raise ValueError("num_eeg_channels must be positive")
        if self.num_classes < 2:
            raise ValueError("num_classes must be at least 2")
        if self.mamba_backend not in {"auto", "torch", "native"}:
            raise ValueError('mamba_backend must be "auto", "torch", or "native"')


def native_mamba_available() -> bool:
    """Return whether locally compiled native Mamba packages are importable."""

    return (
        importlib.util.find_spec("mamba_ssm") is not None
        and importlib.util.find_spec("causal_conv1d") is not None
    )


def _load_native_mamba_cls() -> type[nn.Module]:
    module = importlib.import_module("mamba_ssm.modules.mamba_simple")
    return module.Mamba


def _resolve_mamba_backend(requested_backend: str) -> str:
    if requested_backend == "torch":
        return "torch"
    if requested_backend == "native":
        if not native_mamba_available():
            raise RuntimeError(
                "mamba_backend='native' requires locally compiled mamba-ssm and "
                "causal-conv1d. Run scripts/install_mamba_from_local.ps1 or use "
                "mamba_backend='torch'."
            )
        return "native"
    return "native" if native_mamba_available() else "torch"


def _same_padding_2d(kernel_size: tuple[int, int]) -> tuple[int, int]:
    return kernel_size[0] // 2, kernel_size[1] // 2


class DropPath(nn.Module):
    """Stochastic depth used by the spatial encoder."""

    def __init__(self, drop_prob: float = 0.0) -> None:
        super().__init__()
        self.drop_prob = drop_prob

    def forward(self, x: Tensor) -> Tensor:
        if self.drop_prob == 0.0 or not self.training:
            return x
        keep_prob = 1.0 - self.drop_prob
        shape = (x.shape[0],) + (1,) * (x.ndim - 1)
        random_tensor = keep_prob + torch.rand(shape, dtype=x.dtype, device=x.device)
        random_tensor.floor_()
        return x.div(keep_prob) * random_tensor


class MLP(nn.Module):
    """Feed-forward block used after spatial attention."""

    def __init__(self, features: int, hidden_ratio: int = 4, drop: float = 0.5) -> None:
        super().__init__()
        hidden = features * hidden_ratio
        self.net = nn.Sequential(
            nn.Linear(features, hidden),
            nn.GELU(),
            nn.Dropout(drop),
            nn.Linear(hidden, features),
            nn.Dropout(drop),
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.net(x)


class SpatialAttention(nn.Module):
    """CBAM-style spatial attention over amplitude/phase frequency maps."""

    def __init__(self, kernel_size: tuple[int, int]) -> None:
        super().__init__()
        self.conv = nn.Conv2d(2, 1, kernel_size, padding=_same_padding_2d(kernel_size))
        self.activation = nn.Tanh()

    def forward(self, x: Tensor) -> Tensor:
        source = x
        max_out = torch.max(x, dim=1, keepdim=True).values
        avg_out = torch.mean(x, dim=1, keepdim=True)
        weights = self.activation(self.conv(torch.cat([avg_out, max_out], dim=1)))
        return source + source * weights


class SpatialBlock(nn.Module):
    """Spatial-attention encoder block used for feature enhancement."""

    def __init__(self, dim: int, kernel_size: tuple[int, int], drop_path: float = 0.5) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.spatial_attention = SpatialAttention(kernel_size)
        self.drop_path = DropPath(drop_path) if drop_path > 0 else nn.Identity()
        self.norm2 = nn.LayerNorm(dim)
        self.mlp = MLP(dim)

    def forward(self, x: Tensor) -> Tensor:
        x = x + self.drop_path(self.spatial_attention(self.norm1(x)))
        x = x + self.drop_path(self.mlp(self.norm2(x)))
        return x


class SpatialEncoder(nn.Module):
    """Enhances frequency-domain features before fusion with the U-Net branch."""

    def __init__(self, in_channels: int, depth: int, embed_dim: int, kernel_size: tuple[int, int]) -> None:
        super().__init__()
        self.projection = nn.Conv2d(2, in_channels, kernel_size=1)
        self.norm = nn.LayerNorm(embed_dim)
        self.blocks = nn.Sequential(*[SpatialBlock(embed_dim, kernel_size) for _ in range(depth)])
        self.dropout = nn.Dropout(0.2)

    def forward(self, x: Tensor) -> Tensor:
        x = self.projection(x)
        x = self.dropout(F.relu(self.norm(x)))
        x = self.blocks(x)
        return self.norm(x)


class DoubleConv(nn.Module):
    """Two Conv1d + LayerNorm + GELU stages from the original U-Net branch."""

    def __init__(self, in_channels: int, out_channels: int, sequence_len: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(in_channels, in_channels * 4, kernel_size=3, padding=1, bias=False),
            nn.LayerNorm(sequence_len),
            nn.GELU(),
            nn.Conv1d(in_channels * 4, out_channels, kernel_size=3, padding=1, bias=False),
            nn.LayerNorm(sequence_len),
            nn.GELU(),
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.net(x)


class TorchMambaBlock(nn.Module):
    """Pure-PyTorch selective state-space block inspired by Mamba.

    Input and output shape are ``[batch, sequence, features]``.  The block uses
    projection, depthwise causal convolution, input-dependent gates, and a
    learned diagonal recurrent state update.  It is not a binary-compatible copy
    of ``mamba-ssm``; it is a Windows-portable approximation that preserves the
    model role and tensor interfaces needed by SUMamba.
    """

    def __init__(self, d_model: int, expand: int = 2, conv_kernel: int = 3) -> None:
        super().__init__()
        inner = d_model * expand
        self.in_proj = nn.Linear(d_model, inner * 2)
        self.depthwise_conv = nn.Conv1d(
            inner,
            inner,
            kernel_size=conv_kernel,
            padding=conv_kernel - 1,
            groups=inner,
        )
        self.a_log = nn.Parameter(torch.zeros(inner))
        self.b_proj = nn.Linear(inner, inner)
        self.out_proj = nn.Linear(inner, d_model)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, x: Tensor) -> Tensor:
        residual = x
        x = self.norm(x)
        values, gates = self.in_proj(x).chunk(2, dim=-1)
        values = values.transpose(1, 2)
        values = self.depthwise_conv(values)[..., : x.shape[1]].transpose(1, 2)
        values = F.silu(values)
        gates = F.silu(gates)

        decay = torch.exp(-F.softplus(self.a_log)).view(1, -1)
        input_scale = torch.sigmoid(self.b_proj(values))
        state = torch.zeros(values.shape[0], values.shape[2], dtype=values.dtype, device=values.device)
        outputs: list[Tensor] = []
        for step in range(values.shape[1]):
            state = decay * state + input_scale[:, step, :] * values[:, step, :]
            outputs.append(state)
        y = torch.stack(outputs, dim=1) * gates
        return residual + self.out_proj(y)


class MultiHeadMambaNet(nn.Module):
    """Parallel multi-head Mamba-like feature extractor used in SUMamba."""

    def __init__(self, sequence_len: int, channels: int, num_heads: int, backend: str) -> None:
        super().__init__()
        if sequence_len % num_heads != 0:
            raise ValueError("sequence_len must be divisible by num_heads")
        self.norm1 = nn.LayerNorm(sequence_len)
        self.norm2 = nn.LayerNorm(sequence_len)
        self.conv = nn.Conv1d(channels, channels, kernel_size=3, padding=1)
        self.conv_out = nn.Conv1d(channels, channels, kernel_size=3, padding=1)
        self.activation = nn.GELU()
        self.dropout = nn.Dropout(0.2)
        self.num_heads = num_heads
        self.head_dim = sequence_len // num_heads
        self.backend = backend
        if backend == "native":
            native_mamba_cls = _load_native_mamba_cls()
            self.heads = nn.ModuleList([native_mamba_cls(d_model=self.head_dim) for _ in range(num_heads)])
        else:
            self.heads = nn.ModuleList([TorchMambaBlock(self.head_dim) for _ in range(num_heads)])

    def forward(self, x: Tensor) -> Tensor:
        x = self.dropout(self.activation(self.conv(self.norm1(x))))
        bsz, channels, sequence_len = x.shape
        x = x.view(bsz, channels, self.num_heads, self.head_dim)
        head_outputs = [head(x[:, :, idx, :]) for idx, head in enumerate(self.heads)]
        x = torch.stack(head_outputs, dim=2).view(bsz, channels, sequence_len)
        x = self.dropout(self.activation(self.conv_out(x)))
        return self.dropout(self.norm2(x))


class Down(nn.Module):
    """Down-sampling stage: max-pool, Mamba-like extraction, double conv."""

    def __init__(self, in_channels: int, out_channels: int, sequence_len: int, num_heads: int, backend: str) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.MaxPool1d(2),
            MultiHeadMambaNet(sequence_len, in_channels, num_heads, backend),
            DoubleConv(in_channels, out_channels, sequence_len),
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.net(x)


class Up(nn.Module):
    """Up-sampling stage with skip fusion and Mamba-like extraction."""

    def __init__(self, in_channels: int, out_channels: int, sequence_len: int, num_heads: int, backend: str) -> None:
        super().__init__()
        self.mamba = MultiHeadMambaNet(sequence_len // 2, in_channels, num_heads, backend)
        self.up = nn.ConvTranspose1d(in_channels, out_channels, kernel_size=2, stride=2)
        self.conv = DoubleConv(in_channels, out_channels, sequence_len)

    def forward(self, x1: Tensor, x2: Tensor) -> Tensor:
        x1 = self.up(self.mamba(x1))
        if x1.shape[-1] != x2.shape[-1]:
            x1 = F.interpolate(x1, size=x2.shape[-1], mode="linear", align_corners=False)
        return self.conv(torch.cat([x2, x1], dim=1))


class ChannelAttention(nn.Module):
    """Channel attention to suppress redundant fused EEG-channel features."""

    def __init__(self, channels: int, ratio: int = 6) -> None:
        super().__init__()
        hidden = max(1, channels // ratio)
        self.avg_pool = nn.AdaptiveAvgPool1d(1)
        self.max_pool = nn.AdaptiveMaxPool1d(1)
        self.fc1 = nn.Conv1d(channels, hidden, kernel_size=1, bias=False)
        self.fc2 = nn.Conv1d(hidden, channels, kernel_size=1, bias=False)
        self.activation = nn.ReLU()
        self.gate = nn.Sigmoid()

    def forward(self, x: Tensor) -> Tensor:
        avg_out = self.fc2(self.activation(self.fc1(self.avg_pool(x))))
        max_out = self.fc2(self.activation(self.fc1(self.max_pool(x))))
        return x * self.gate(avg_out + max_out)


class SUMamba(nn.Module):
    """SUMamba classifier reproduced with Windows-compatible PyTorch layers.

    The forward input must be shaped ``[batch, 2, eeg_channels, freq_bins]``.
    Channel 0 is FFT amplitude and channel 1 is FFT phase.
    """

    def __init__(self, config: SUMambaConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.mamba_backend = _resolve_mamba_backend(config.mamba_backend)
        channels = config.num_eeg_channels
        freq = config.freq_bins
        full_len = freq * 2

        self.inc = DoubleConv(channels, channels, full_len)
        self.down1 = Down(channels, channels * 2, freq, config.num_heads, self.mamba_backend)
        self.down2 = Down(channels * 2, channels * 4, freq // 2, config.num_heads, self.mamba_backend)
        self.down3 = Down(channels * 4, channels * 8, freq // 4, config.num_heads, self.mamba_backend)
        self.up1 = Up(channels * 8, channels * 4, freq // 2, config.num_heads, self.mamba_backend)
        self.up2 = Up(channels * 4, channels * 2, freq, config.num_heads, self.mamba_backend)
        self.up3 = Up(channels * 2, channels, full_len, config.num_heads, self.mamba_backend)

        self.spatial = SpatialEncoder(
            in_channels=config.spatial_channels,
            depth=config.spatial_depth,
            embed_dim=freq,
            kernel_size=config.spatial_kernel_size,
        )
        self.reduce_after_unet = nn.Conv1d(channels, channels, kernel_size=2, stride=2)
        self.channel_attention = ChannelAttention(channels)
        self.flatten = nn.Flatten()
        self.dropout = nn.Dropout(config.dropout)
        self.activation = nn.GELU()
        self.classifier = nn.Sequential(
            nn.Linear(channels * freq, config.embed_dim * 5),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.embed_dim * 5, config.embed_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.embed_dim, config.num_classes),
        )

    def forward(self, x: Tensor) -> Tensor:
        if x.ndim != 4 or x.shape[1] != 2:
            raise ValueError("SUMamba expects [batch, 2, eeg_channels, freq_bins] input")
        if x.shape[2] != self.config.num_eeg_channels or x.shape[3] != self.config.freq_bins:
            raise ValueError(
                "input eeg_channels/freq_bins do not match SUMambaConfig: "
                f"got {tuple(x.shape[2:])}, expected "
                f"{(self.config.num_eeg_channels, self.config.freq_bins)}"
            )

        spatial = self.spatial(x).mean(dim=1)
        unet = self.inc(torch.cat([x[:, 0, :, :], x[:, 1, :, :]], dim=2))
        skip1 = unet
        skip2 = self.dropout(self.down1(skip1))
        skip3 = self.dropout(self.down2(skip2))
        bottleneck = self.dropout(self.down3(skip3))
        unet = self.dropout(self.up1(bottleneck, skip3))
        unet = self.dropout(self.up2(unet, skip2))
        unet = self.dropout(self.up3(unet, skip1))
        unet = self.dropout(self.reduce_after_unet(unet))
        fused = self.dropout(self.channel_attention(unet + spatial))
        return self.classifier(self.flatten(fused))


def make_sumamba(
    num_classes: int = 40,
    num_eeg_channels: int = 30,
    freq_bins: int = 256,
    **overrides: int | float | tuple[int, int],
) -> SUMamba:
    """Factory for scripts that need a concise model constructor."""

    config = SUMambaConfig(
        num_classes=num_classes,
        num_eeg_channels=num_eeg_channels,
        freq_bins=freq_bins,
        **overrides,
    )
    return SUMamba(config)
