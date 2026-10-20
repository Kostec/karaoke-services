"""Проверка GPU в контейнере worker (история 55).

`python -m karaoke_worker gpucheck` печатает версии torch и CUDA, список архитектур, GPU и VRAM,
результат умножения тензоров на cuda, CUDA-устройства ctranslate2 и поддержку int8,
затем проверяет правки UltraSinger (selfcheck). Код выхода 0 — только если всё прошло.

`check()` возвращает словарь для записи в БД при старте воркера:
{ok, name, vram_mb, error, torch, cuda, arch_list, matmul_ok, ct2_devices, ct2_int8}.
"""

from __future__ import annotations

from typing import Any

REQUIRED_ARCH = "sm_61"  # GTX 1080 (Pascal)


def runnable_arch(arch_list: list[str], major: int, minor: int) -> str | None:
    """Архитектура из сборки torch, чей машинный код исполняется на GPU major.minor.

    Код sm_XY исполняется на устройстве X.Z при Z >= Y (то же поколение). Колёса torch cu126
    несут sm_60, и на GTX 1080 (6.1) работает он. None — кода для этого GPU нет.
    """
    best = None
    for a in arch_list:
        if a.startswith("sm_") and a[3:].isdigit() and len(a) >= 5:
            amaj, amin = int(a[3:-1]), int(a[-1])
            if amaj == major and amin <= minor and (best is None or amin > int(best[-1])):
                best = a
    return best
CT2_COMPUTE_TYPE = "int8"  # для GTX 1080 только int8, никогда float16


def check() -> dict[str, Any]:
    info: dict[str, Any] = {"ok": False, "name": None, "vram_mb": None, "error": None, "torch": None,
                            "cuda": None, "arch_list": [], "matmul_ok": False, "ct2_devices": 0,
                            "ct2_int8": False}
    errors: list[str] = []
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 — сообщение уходит пользователю
        info["error"] = f"PyTorch не импортируется: {exc}"
        return info

    info["torch"] = torch.__version__
    info["cuda"] = torch.version.cuda
    if not torch.cuda.is_available():
        errors.append("torch.cuda.is_available() == False: GPU не виден в контейнере "
                      "(проверь драйвер NVIDIA и GPU-резервирование в compose)")
    else:
        info["arch_list"] = torch.cuda.get_arch_list()
        props = torch.cuda.get_device_properties(0)
        info["kernel_arch"] = runnable_arch(info["arch_list"], props.major, props.minor)
        if info["kernel_arch"] is None:
            errors.append(f"в PyTorch нет кода для этого GPU (compute capability {props.major}.{props.minor}); "
                          f"есть только {' '.join(info['arch_list'])}")
        info["name"] = props.name
        info["vram_mb"] = props.total_memory // (1024 * 1024)
        info["capability"] = f"{props.major}.{props.minor}"
        try:
            a = torch.arange(1.0, 7.0).reshape(2, 3)
            b = torch.arange(1.0, 7.0).reshape(3, 2)
            got = (a.cuda() @ b.cuda()).cpu()
            expected = torch.tensor([[22.0, 28.0], [49.0, 64.0]])  # посчитано вручную
            info["matmul_ok"] = bool(torch.equal(got, expected))
            info["matmul"] = got.tolist()
            if not info["matmul_ok"]:
                errors.append(f"умножение тензоров на cuda дало {got.tolist()}, ожидалось {expected.tolist()}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"умножение тензоров на cuda упало: {exc}")

    try:
        import ctranslate2
        info["ct2_version"] = ctranslate2.__version__
        info["ct2_devices"] = ctranslate2.get_cuda_device_count()
        if info["ct2_devices"] < 1:
            errors.append("ctranslate2 не видит CUDA-устройств")
        else:
            types = sorted(ctranslate2.get_supported_compute_types("cuda"))
            info["ct2_compute_types"] = types
            info["ct2_int8"] = CT2_COMPUTE_TYPE in types
            if not info["ct2_int8"]:
                errors.append(f"ctranslate2 не поддерживает {CT2_COMPUTE_TYPE} на GPU (есть: {', '.join(types)})")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ctranslate2: {exc}")

    info["error"] = "; ".join(errors) or None
    info["ok"] = not errors
    return info


def main() -> int:
    from karaoke_worker import selfcheck

    info = check()
    print(f"PyTorch:            {info['torch'] or '—'}")
    print(f"CUDA (torch):       {info['cuda'] or '—'}")
    print(f"Архитектуры:        {' '.join(info['arch_list']) or '—'}"
          f"  (для этого GPU исполняется: {info.get('kernel_arch') or 'НЕТ'})")
    vram = f"{info['vram_mb']} МБ" if info["vram_mb"] else "—"
    cap = f", compute capability {info['capability']}" if info.get("capability") else ""
    print(f"GPU:                {info['name'] or '—'}{cap}, VRAM {vram}")
    print(f"Тензоры на cuda:    {'OK ' + str(info.get('matmul')) if info['matmul_ok'] else 'ОШИБКА'}")
    print(f"ctranslate2:        {info.get('ct2_version', '—')}, CUDA-устройств: {info['ct2_devices']}, "
          f"int8: {'да' if info['ct2_int8'] else 'НЕТ'}"
          + (f" (типы: {', '.join(info['ct2_compute_types'])})" if info.get("ct2_compute_types") else ""))
    print("--- правки UltraSinger ---")
    patches_rc = selfcheck.main()
    if info["ok"] and patches_rc == 0:
        print("gpucheck: OK — GPU готов к генерации")
        return 0
    if not info["ok"]:
        print(f"gpucheck: ОШИБКА — {info['error']}")
    else:
        print("gpucheck: ОШИБКА — пропали правки UltraSinger (см. выше)")
    return 1
