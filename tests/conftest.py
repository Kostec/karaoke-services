"""Общее для всех тестов: ``tests/`` в ``sys.path`` — общие фейки (``fakes_http``) импортируются
напрямую (pytest запускается с ``--import-mode=importlib``, сам он папку не добавляет)."""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS = str(Path(__file__).resolve().parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)


import pytest  # noqa: E402

from karaoke_core import musiclink  # noqa: E402

# DNS в тестах не трогаем: classify считает все хосты нерезолвящимися (проверку адресов
# домашней сети по DNS тесты задают своим резолвером). Модульно — до импорта тестов,
# у которых classify зовётся при загрузке модуля.
musiclink.RESOLVER = lambda host: []


@pytest.fixture(autouse=True)
def _no_busy_waits(monkeypatch):
    """Паузы между повторами замены занятого файла на шаре в тестах — нулевые
    (их число и порядок проверяет tests/core/test_storage.py)."""
    from karaoke_core.storage import base
    monkeypatch.setattr(base, "BUSY_RETRY_DELAYS", (0,) * len(base.BUSY_RETRY_DELAYS))
