"""Проверка при сборке: PyTorch собран с CUDA и с кодом, который исполняется на GTX 1080 (Pascal, 6.1).

GPU при сборке недоступен, поэтому torch.cuda.get_arch_list() вернул бы пустой список;
список архитектур берём из флагов компиляции (_cuda_getArchFlags) — это тот же источник.
Правило совместимости одно на весь проект: karaoke_worker.gpucheck.runnable_arch
(рядом со скриптом при сборке лежит копия gpucheck.py).
"""

import sys

import torch

try:
    from karaoke_worker.gpucheck import runnable_arch
except ImportError:  # шаг сборки до установки пакета: копия gpucheck.py рядом со скриптом
    from gpucheck import runnable_arch

GPU = (6, 1)  # GTX 1080
flags = torch._C._cuda_getArchFlags() if hasattr(torch._C, "_cuda_getArchFlags") else ""
arch = flags.split()
print(f"torch {torch.__version__}, CUDA {torch.version.cuda}, архитектуры: {' '.join(arch) or '—'}")

if not torch.version.cuda:
    sys.exit("ОШИБКА СБОРКИ: установлен PyTorch без CUDA. Нужен torch с индекса cu126.")
kernel = runnable_arch(arch, *GPU)
if kernel is None:
    sys.exit(
        f"ОШИБКА СБОРКИ: в PyTorch {torch.__version__} нет кода для GTX 1080 (Pascal, sm_61): "
        f"нужна sm_61 или совместимая sm_60. Есть: {' '.join(arch) or 'ничего'}. "
        f"Ставь torch с индекса https://download.pytorch.org/whl/cu126."
    )
print(f"Pascal (GTX 1080, 6.1): OK, исполняется код {kernel}")
