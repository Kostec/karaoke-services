"""Проверка при сборке: PyTorch собран с CUDA 12.6 и с кодом для Pascal (sm_61, GTX 1080).

GPU при сборке недоступен, поэтому torch.cuda.get_arch_list() вернул бы пустой список;
список архитектур берём из флагов компиляции (_cuda_getArchFlags) — это тот же источник.
"""

import sys

import torch

# GTX 1080 — compute capability 6.1. Машинный код sm_6X исполняется на любом 6.Y при Y >= X
# (одно поколение Pascal), поэтому подходит sm_61 или sm_60. Официальные колёса cu126
# содержат sm_60 (sm_61 отдельно не собирается) — этого достаточно.
REQUIRED = "sm_61"
COMPATIBLE = ("sm_61", "sm_60")
flags = torch._C._cuda_getArchFlags() if hasattr(torch._C, "_cuda_getArchFlags") else ""
arch = flags.split()
print(f"torch {torch.__version__}, CUDA {torch.version.cuda}, архитектуры: {' '.join(arch) or '—'}")

if not torch.version.cuda:
    sys.exit("ОШИБКА СБОРКИ: установлен PyTorch без CUDA. Нужен torch с индекса cu126.")
if not any(a in arch for a in COMPATIBLE):
    sys.exit(
        f"ОШИБКА СБОРКИ: в PyTorch {torch.__version__} нет кода для {REQUIRED} (GTX 1080, Pascal): "
        f"нужна sm_61 или совместимая sm_60. "
        f"Есть: {' '.join(arch) or 'ничего'}. Ставь torch с индекса https://download.pytorch.org/whl/cu126."
    )
print(f"Pascal ({REQUIRED}): OK, исполняется код {next(a for a in COMPATIBLE if a in arch)}")
