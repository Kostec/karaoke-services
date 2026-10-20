"""CLI воркера: python -m karaoke_worker <команда>.

Команды:
  gpucheck   проверка GPU, PyTorch, ctranslate2 и правок UltraSinger (код 0 — всё в порядке)
  selfcheck  только проверка правок UltraSinger из ветки karaoke-local
  run        исполнитель очереди заданий (по умолчанию в контейнере)
"""

from __future__ import annotations

import argparse
import sys


def _run(_args: argparse.Namespace) -> int:
    # Место для исполнителя очереди (karaoke_worker.runner.run_forever) — добавляет таск runner.
    try:
        from karaoke_worker import runner  # type: ignore[attr-defined]
    except ImportError:
        import signal

        print("worker: исполнитель заданий ещё не установлен в этот образ; ожидаю остановки", flush=True)
        signal.pause()
        return 0
    return runner.run_forever() or 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="karaoke_worker", description="Воркер karaoke-services")
    sub = parser.add_subparsers(dest="command", required=True, metavar="команда")
    sub.add_parser("gpucheck", help="проверить GPU, PyTorch, ctranslate2 и правки UltraSinger").set_defaults(
        func=lambda a: __import__("karaoke_worker.gpucheck", fromlist=["main"]).main())
    sub.add_parser("selfcheck", help="проверить правки UltraSinger (ветка karaoke-local)").set_defaults(
        func=lambda a: __import__("karaoke_worker.selfcheck", fromlist=["main"]).main())
    sub.add_parser("run", help="исполнять задания из очереди").set_defaults(func=_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
