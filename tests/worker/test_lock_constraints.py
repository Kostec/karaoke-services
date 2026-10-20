"""lock_constraints: версии из uv.lock UltraSinger, кроме наших пинов и всегда свежего yt-dlp."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "worker" / "build" / "lock_constraints.py"


def load():
    spec = importlib.util.spec_from_file_location("lock_constraints", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_yt_dlp_is_not_pinned_but_other_lock_versions_are(tmp_path):
    src = tmp_path / "export.txt"
    src.write_text(
        "# uv export\n"
        "yt-dlp==2026.2.21\n"
        "yt_dlp_ejs==0.4.0\n"
        "swift-f0==0.1.2\n"
        "torch==2.8.0\n"
        "nvidia-cudnn-cu12==9.1.0\n",
        encoding="utf-8",
    )
    dst = tmp_path / "constraints.txt"
    load().main(str(src), str(dst))
    lines = [l for l in dst.read_text("utf-8").splitlines() if l and not l.startswith("#")]
    assert "swift-f0==0.1.2" in lines
    assert "torch==2.8.0+cu126" in lines and "torch==2.8.0" not in lines
    assert not any(l.lower().replace("_", "-").startswith("yt-dlp") for l in lines)
    assert not any(l.startswith("nvidia-") for l in lines)
