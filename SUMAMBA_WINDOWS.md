# SUMamba Windows 复现说明

本文档说明本仓库新增的 `sumamba_windows` 版本如何按论文 **“SUMamba: A Mamba-based deep learning model with multi-scale feature fusion for SSVEP classification”** 和作者 GitHub 代码的主要结构复现模型，同时给出两条 Windows 路线：

1. **默认稳定路线**：使用纯 PyTorch Mamba-like 后端，不编译 `mamba-ssm` / `causal-conv1d`。
2. **可选本地编译路线**：如果你本机确实有 `D:\ST\SUMamba` 下的 `mamba-ssm` 与 `causal-conv1d` 源码，并且 Windows C++/CUDA 编译环境完整，可以尝试本地编译；编译失败时直接跳过，模型会继续使用纯 PyTorch 后端。

## 复现依据

论文摘要说明 SUMamba 使用 SSVEP 频域幅值/相位、空间注意力编码器、多尺度 U-Net 融合、Mamba 模块和通道注意力；ScienceDirect 页面给出的作者代码地址是 `https://github.com/dlyres/SUMamba`。作者仓库中的 `model/UnetMamba.py` 依赖 `mamba_ssm.modules.mamba_simple.Mamba`，`requirements.txt` 也固定了 `mamba-ssm==1.1.3.post1` 与 `causal-conv1d==1.1.1`，这两项通常需要 Linux/CUDA 编译环境。

## Windows 版的核心改动

- 保留输入格式：`[batch, 2, eeg_channels, freq_bins]`，其中 `2` 分别表示 FFT 幅值和相位。
- 保留空间增强分支：`SpatialEncoder` 使用 CBAM 风格空间注意力 + MLP block。
- 保留 U-Net 多尺度融合分支：`DoubleConv`、`Down`、`Up`、skip connection 与原始结构对应。
- 保留多头序列建模位置：`MultiHeadMambaNet` 仍把频率序列切分为多个 head 并逐 head 建模。
- 默认将 Linux 扩展版 Mamba 替换为纯 PyTorch `TorchMambaBlock`：使用投影、深度可分离卷积、门控和对角状态空间递推近似 Mamba 的选择性状态空间作用。
- 新增 `mamba_backend` 参数：`"torch"` 强制使用纯 PyTorch；`"auto"` 在本地编译包可用时使用 native，否则回退；`"native"` 强制使用本地编译的 `mamba-ssm`。
- 保留分类前通道注意力：`ChannelAttention` 对融合后的 EEG channel 特征重新加权。

## 文件结构

```text
sumamba_windows/
  __init__.py                    # 对外导出 SUMamba、配置、后端检测与预处理函数
  model.py                       # Windows 兼容 SUMamba 模型主体
  preprocessing.py               # FFT 幅值/相位和 FB-SUMamba 风格 filter-bank 特征辅助函数
  requirements-windows.txt       # Windows 运行依赖提示
  train_demo.py                  # 最小训练 smoke demo
scripts/
  setup_sumamba_windows.bat      # 一键创建虚拟环境并安装依赖
  install_mamba_from_local.ps1   # 可选：从 D:\ST\SUMamba 本地源码尝试编译 native Mamba 依赖
tests/
  test_sumamba_windows_static.py
SUMAMBA_WINDOWS.md
```

## 一键安装（Windows .bat）

推荐直接运行新增的批处理脚本，它会自动：

1. 在项目根目录创建或复用 `.venv` 虚拟环境。
2. 升级 `pip / setuptools / wheel`。
3. 默认从 CPU wheel 源安装 PyTorch；如果传入 `--cuda128/--cuda126/--cuda118`，则改装对应 CUDA wheel。
4. 安装 `sumamba_windows/requirements-windows.txt` 中的辅助依赖。
5. 做一次 `torch` 和 `sumamba_windows` 导入检查。

```bat
scripts\setup_sumamba_windows.bat
```

如果你的电脑有 NVIDIA GPU，尤其是 RTX 50 系列 / RTX 5090，建议优先尝试 CUDA 12.8 wheel：

```bat
scripts\setup_sumamba_windows.bat --rtx5090
```

`--rtx5090` 是 `--cuda128` 的别名；你也可以直接运行：

```bat
scripts\setup_sumamba_windows.bat --cuda128
```

如果你的显卡驱动较旧或 PyTorch 官网建议使用其他 CUDA wheel，可改用：

```bat
scripts\setup_sumamba_windows.bat --cuda126
scripts\setup_sumamba_windows.bat --cuda118
```

安装完成后，如果你在 **CMD** 中，激活环境：

```bat
call .venv\Scripts\activate.bat
```

如果你在 **PowerShell / PyCharm Terminal 的 PS 提示符** 中，不能使用 `call`，请用：

```powershell
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 执行策略拦截激活脚本，可以临时放开当前进程：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

也可以完全不激活，直接调用虚拟环境里的 Python：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

如果你想同时尝试从 `D:\ST\SUMamba` 本地源码编译 native `mamba-ssm / causal-conv1d`，可以运行：

```bat
scripts\setup_sumamba_windows.bat --native
```

可选环境变量：

- `VENV_DIR`：虚拟环境目录，默认 `.venv`。
- `PYTHON_EXE`：指定 Python 命令；不指定时优先使用 `py -3.11`，否则使用 `python`。
- `TORCH_INDEX_URL`：PyTorch wheel 源，默认 `https://download.pytorch.org/whl/cpu`。也可用 `--rtx5090`、`--cuda128`、`--cuda126`、`--cuda118` 自动切换到对应 CUDA wheel 源。
- `FORCE_REINSTALL_TORCH=1`：强制重装 torch；从 CPU 版切换到 CUDA 版时会自动启用。
- `INSTALL_NATIVE=1`：等价于传入 `--native`。
- `SUMAMBA_SOURCE`：native 源码根目录，默认 `D:\ST\SUMamba`。

## 手动安装建议（Windows）

如果不使用 `.bat`，也可以手动创建虚拟环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

CPU 版 PyTorch：

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

如果你的 Windows 机器有 NVIDIA GPU，请按 PyTorch 官网选择与你 CUDA 版本匹配的安装命令。当前脚本内置了 `--cuda128`、`--cuda126`、`--cuda118` 三个常见入口；安装后用 `python -c "import torch; print(torch.__version__, torch.cuda.is_available())"` 验证是否启用 GPU。默认纯 PyTorch 后端不需要安装 `mamba-ssm`、`causal-conv1d`、`triton` 或 Linux 编译工具链。

## 可选：从 `D:\ST\SUMamba` 本地源码编译 mamba-ssm / causal-conv1d

我无法在当前 Linux 容器中直接访问你的 Windows 路径 `D:\ST\SUMamba`，所以不能替你验证这一步是否一定成功。仓库中提供了 **best-effort** PowerShell 脚本：只有当本地源码与编译工具链满足条件时才安装 native 后端；如果不能编译，默认会跳过并继续使用纯 PyTorch 后端，符合“如果不能就取消这一步操作”的要求。

建议先安装/准备：

- 与 PyTorch 匹配的 CUDA Toolkit（如果你的本地 `mamba-ssm` / `causal-conv1d` 需要 CUDA 编译）。
- Visual Studio Build Tools，并从 **x64 Native Tools Command Prompt for VS** 启动 PowerShell，确保 `cl.exe` 可用。
- Python 环境中已安装 PyTorch。

尝试编译：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_mamba_from_local.ps1 -SourceRoot D:\ST\SUMamba
```

如果你的两个依赖仓库不在默认子目录，可显式指定：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_mamba_from_local.ps1 `
  -CausalConv1dPath D:\ST\SUMamba\causal-conv1d `
  -MambaSsmPath D:\ST\SUMamba\mamba-ssm
```

默认模式下，脚本遇到找不到源码、缺少 PyTorch、编译失败或导入失败时会输出 warning 后退出，不会破坏当前纯 PyTorch 路线。若你希望 CI 或本地调试时失败即报错，可添加 `-Strict`。

编译成功后可以强制使用 native 后端：

```python
from sumamba_windows import SUMamba, SUMambaConfig, native_mamba_available

print(native_mamba_available())
model = SUMamba(SUMambaConfig(mamba_backend="native"))
```

也可以用 `mamba_backend="auto"`：当 native 包可导入时自动使用 native，否则回退到纯 PyTorch。

## 快速使用

```python
import torch
from sumamba_windows import SUMamba, SUMambaConfig, fft_amplitude_phase

# 假设原始 EEG: [batch, eeg_channels, time_samples]
eeg = torch.randn(4, 30, 512)
x = fft_amplitude_phase(eeg, freq_bins=256)

model = SUMamba(SUMambaConfig(num_classes=40, num_eeg_channels=30, freq_bins=256, mamba_backend="torch"))
logits = model(x)
print(logits.shape)  # torch.Size([4, 40])
```

运行最小训练示例：

```powershell
python -m sumamba_windows.train_demo --classes 12 --channels 8 --samples 16 --epochs 1 --mamba-backend torch
```

## 迁移真实 SSVEP 数据集

1. 按原论文/原仓库方式做通道选择、时间窗截取和标签整理。
2. 将每个 trial 整理成 `[eeg_channels, time_samples]`，批量后为 `[batch, eeg_channels, time_samples]`。
3. 调用 `fft_amplitude_phase(eeg, freq_bins=256)` 得到 SUMamba 输入。
4. 对 BETA/Benchmark 常见 40 类任务，可使用：

```python
config = SUMambaConfig(num_classes=40, num_eeg_channels=30, freq_bins=256, mamba_backend="torch")
model = SUMamba(config)
```

5. 对 12 类或 8 通道数据，只需调整 `num_classes` 与 `num_eeg_channels`。


## Benchmark 数据集训练复现

新增的 `sumamba_windows/ssvep_dataset.py` 和 `sumamba_windows/train_benchmark.py` 用于按 Benchmark 数据集的常用 subject-dependent 思路训练：每个 subject 有 6 个 block/trial，脚本默认做 6 折 block-wise cross-validation，即每次留 1 个 block 测试、其余 5 个 block 训练。

数据目录需要包含官方 MATLAB 文件：

```text
D:\datasets\Benchmark\S1.mat
D:\datasets\Benchmark\S2.mat
...
D:\datasets\Benchmark\S35.mat
```

先用一个被试和一个 fold 做 smoke test：

```powershell
.\.venv\Scripts\python.exe -m sumamba_windows.train_benchmark `
  --data-root D:\datasets\Benchmark `
  --subjects 1 `
  --folds 0 `
  --epochs 2 `
  --batch-size 64 `
  --mamba-backend torch `
  --print-channels
```

确认能跑通后，训练一个被试的 6 折：

```powershell
.\.venv\Scripts\python.exe -m sumamba_windows.train_benchmark `
  --data-root D:\datasets\Benchmark `
  --subjects 1 `
  --folds 0-5 `
  --epochs 100 `
  --batch-size 64 `
  --channels posterior30 `
  --amp `
  --save-checkpoints `
  --print-channels
```

完整 Benchmark 复现可运行全部 35 个被试：

```powershell
.\.venv\Scripts\python.exe -m sumamba_windows.train_benchmark `
  --data-root D:\datasets\Benchmark `
  --subjects 1-35 `
  --folds 0-5 `
  --epochs 100 `
  --batch-size 64 `
  --amp `
  --save-checkpoints
```

脚本默认窗口为 `start_sample=125, end_sample=625`，即 250 Hz 采样率下 0.5 s 后开始的 2 s 片段；默认 `freq_bins=256`、`num_classes=40`、`num_heads=2`、`embed_dim=256`。

通道选择已从早期的 `first30` 改为默认 `posterior30`：脚本会优先读取数据目录中的 `64-channels.loc`，并选择 CP/P/PO/O/CB 等后部 30 个通道；这比前 30 个额区/中央区通道更适合 SSVEP。可用参数：

- `--channels posterior30`：默认，CP5..CB2，30 通道。
- `--channels occipital`：PO/O 区小通道集合。
- `--channels parieto_occipital`：P7..O2，20 通道。
- `--channels POZ,OZ,O1,O2`：直接按 `64-channels.loc` 中的通道名选择。
- `--channels 52-62`：直接传零基索引范围。

建议加 `--print-channels` 检查实际解析出的通道名。

## FB-SUMamba 扩展

`make_filter_bank_features()` 用于已经完成滤波的多个频带：

```python
from sumamba_windows import make_filter_bank_features

# bands 是多个 [batch, eeg_channels, time_samples] Tensor，例如 5 个子带
fb_x = make_filter_bank_features(bands, freq_bins=256)
# 形状: [batch, bands, 2, eeg_channels, freq_bins]
```

你可以对每个 band 共享一个 `SUMamba` 前向，然后平均 logits 或学习 band 权重，以复现论文中的 FB-SUMamba 思路。

## 注意事项

该实现目标是“Windows 可运行的结构复现”。纯 PyTorch 后端不是 `mamba-ssm` CUDA kernel 的逐算子等价替代，因此重新训练后的数值结果不会与作者 Linux 环境权重逐 bit 一致；如果论文作者发布预训练权重，也不能直接无损加载到纯 PyTorch Mamba 替代块中。若本地 native 编译成功并使用 `mamba_backend="native"`，模型中的 Mamba head 会调用已安装的 `mamba_ssm.modules.mamba_simple.Mamba`，但 Windows 上能否编译成功仍取决于你本地源码版本、PyTorch/CUDA/MSVC 组合。
