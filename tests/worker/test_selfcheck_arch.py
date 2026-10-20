"""gpucheck: какая архитектура из сборки torch исполняется на GPU (GTX 1080 = 6.1). Без torch."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from karaoke_worker.gpucheck import runnable_arch  # noqa: E402

CU126_WHEEL = ["sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90"]  # torch 2.8.0+cu126


def test_gtx1080_runs_sm60_code_from_cu126_wheel():
    assert runnable_arch(CU126_WHEEL, 6, 1) == "sm_60"


def test_exact_sm61_preferred_when_present():
    assert runnable_arch(["sm_60", "sm_61", "sm_70"], 6, 1) == "sm_61"


def test_no_code_for_pascal_without_sm6x():
    # колёса cu128 для Linux: начинаются с sm_70
    assert runnable_arch(["sm_70", "sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"], 6, 1) is None


def test_newer_minor_of_same_major_does_not_run_on_older_gpu():
    assert runnable_arch(["sm_62"], 6, 1) is None
