"""Ограничения для установки зависимостей UltraSinger: версии из его uv.lock + наши пины.

Вход — вывод `uv export --frozen --no-hashes` по uv.lock UltraSinger. Из него убираются пакеты,
которые задаём мы: torch/torchaudio/torchvision (сборка cu126 вместо PyPI-сборки из lock),
связанные с ними nvidia-*-cu12 и triton (их версии диктует torch cu126), numpy (у нас numpy<2.5).
Остальные версии — ровно как в uv.lock (например swift-f0 0.1.2: в 0.3.0 другая сигнатура SwiftF0).
Использование: python lock_constraints.py <export.txt> <constraints.txt>
"""

import re
import sys

OURS = {
    "torch": "torch==2.8.0+cu126",
    "torchaudio": "torchaudio==2.8.0+cu126",
    "torchvision": "torchvision==0.23.0+cu126",
    "numpy": "numpy<2.5",
}


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def overridden(name: str) -> bool:
    n = norm(name)
    return n in OURS or n.startswith("nvidia-") or n == "triton"


def main(src: str, dst: str) -> None:
    kept, dropped = [], []
    for raw in open(src, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith(("#", "-")):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if not m:
            continue
        (dropped if overridden(m.group(1)) else kept).append(line)
    with open(dst, "w", encoding="utf-8") as f:
        f.write("# Из uv.lock UltraSinger (без пакетов, которые задаём мы):\n")
        f.write("\n".join(kept) + "\n")
        f.write("# Наши пины:\n" + "\n".join(OURS.values()) + "\n")
    print(f"uv.lock: {len(kept)} версий зафиксировано; заменены нашими пинами: "
          + ", ".join(d.split(";")[0].strip() for d in dropped))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
