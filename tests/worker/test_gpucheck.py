"""gpucheck.check(): итог проверки GPU на фейковых torch и ctranslate2 (настоящий GPU не нужен).

Настоящая GTX 1080 проверяется `docker --context desktop-linux compose run --rm worker gpucheck`.
"""

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from karaoke_worker import gpucheck  # noqa: E402

CONTRACT_KEYS = {"ok", "name", "vram_mb", "error", "torch", "cuda", "arch_list", "kernel_arch", "capability",
                 "matmul_ok", "matmul", "ct2_version", "ct2_devices", "ct2_int8", "ct2_compute_types"}
CU126_ARCH = ["sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90"]


class FakeTensor:
    def __init__(self, rows):
        self.rows = rows

    def reshape(self, n, m):
        flat = [x for r in self.rows for x in r]
        return FakeTensor([flat[i * m:(i + 1) * m] for i in range(n)])

    def cuda(self):
        return self

    def cpu(self):
        return self

    def __matmul__(self, other):
        cols = list(zip(*other.rows))
        return FakeTensor([[sum(a * b for a, b in zip(r, c)) for c in cols] for r in self.rows])

    def tolist(self):
        return [list(r) for r in self.rows]


def fake_torch(*, cuda=True, arch=CU126_ARCH, capability=(6, 1)):
    t = types.ModuleType("torch")
    t.__version__ = "2.8.0+cu126"
    t.version = types.SimpleNamespace(cuda="12.6")
    props = types.SimpleNamespace(name="NVIDIA GeForce GTX 1080", total_memory=8191 * 1024 * 1024,
                                  major=capability[0], minor=capability[1])
    t.cuda = types.SimpleNamespace(is_available=lambda: cuda, get_arch_list=lambda: list(arch),
                                   get_device_properties=lambda i: props)
    t.arange = lambda a, b: FakeTensor([[float(x) for x in range(int(a), int(b))]])
    t.tensor = lambda rows: FakeTensor(rows)
    t.equal = lambda x, y: x.tolist() == y.tolist()
    return t


def fake_ct2(*, devices=1, types_=("float32", "int8", "int8_float32")):
    m = types.ModuleType("ctranslate2")
    m.__version__ = "4.8.3"
    m.get_cuda_device_count = lambda: devices
    m.get_supported_compute_types = lambda device: set(types_)
    return m


@pytest.fixture
def modules(monkeypatch):
    def install(torch=None, ct2=None):
        monkeypatch.setitem(sys.modules, "torch", torch)  # None → ImportError при import
        monkeypatch.setitem(sys.modules, "ctranslate2", ct2 if ct2 is not None else fake_ct2())
    return install


def test_full_success_returns_ok_and_every_contract_key(modules):
    modules(torch=fake_torch())

    info = gpucheck.check()

    assert set(info) == CONTRACT_KEYS
    assert info["ok"] is True and info["error"] is None
    assert info["name"] == "NVIDIA GeForce GTX 1080" and info["vram_mb"] == 8191
    assert info["kernel_arch"] == "sm_60" and info["capability"] == "6.1"
    assert info["matmul_ok"] is True and info["matmul"] == [[22.0, 28.0], [49.0, 64.0]]
    assert info["ct2_devices"] == 1 and info["ct2_int8"] is True


def test_no_torch(modules):
    modules(torch=None)

    info = gpucheck.check()

    assert set(info) == CONTRACT_KEYS
    assert info["ok"] is False and "PyTorch не импортируется" in info["error"]


def test_no_cuda(modules):
    modules(torch=fake_torch(cuda=False))

    info = gpucheck.check()

    assert info["ok"] is False and "GPU не виден" in info["error"]


def test_no_compatible_arch(modules):
    modules(torch=fake_torch(arch=["sm_70", "sm_75", "sm_80", "sm_86", "sm_90", "sm_120"]))

    info = gpucheck.check()

    assert info["ok"] is False and info["kernel_arch"] is None
    assert "нет кода для этого GPU" in info["error"] and "6.1" in info["error"]


def test_ctranslate2_without_int8(modules):
    modules(torch=fake_torch(), ct2=fake_ct2(types_=("float32",)))

    info = gpucheck.check()

    assert info["ok"] is False and info["ct2_int8"] is False
    assert "не поддерживает int8" in info["error"]


def test_ctranslate2_without_devices(modules):
    modules(torch=fake_torch(), ct2=fake_ct2(devices=0))

    info = gpucheck.check()

    assert info["ok"] is False and "ctranslate2 не видит CUDA" in info["error"]
