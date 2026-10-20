"""Фейковый ``python -m demucs.separate`` (DEMUCS_CMD): проверяет ключи two-stems htdemucs cuda
и кладёт ``<out>/htdemucs/<stem>/no_vocals.wav``."""

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    need = [("--two-stems", "vocals"), ("-n", "htdemucs"), ("-d", "cuda")]
    for key, value in need:
        if key not in argv or argv[argv.index(key) + 1] != value:
            print(f"bad args: {argv}", flush=True)
            return 2
    out = Path(argv[argv.index("--out") + 1])
    src = Path(argv[-1])
    for i in range(5):
        sys.stderr.write(f"\r{(i + 1) * 20:3d}%|{'#' * (i + 1)}|")
    sys.stderr.write("\n")
    dest = out / "htdemucs" / src.stem
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "no_vocals.wav").write_bytes(b"RIFF fake no_vocals " + src.read_bytes()[:16])
    (dest / "vocals.wav").write_bytes(b"RIFF fake vocals")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
