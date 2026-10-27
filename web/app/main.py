"""FastAPI-приложение karaoke-services (web). Запуск: ``uvicorn --factory app.main:create_app``.

Веб не исполняет задания: он только ставит их в БД (таблица jobs), воркер забирает сам.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api_bulk import router as bulk_router  # library-tools 06
from .api_import import purge_imports, router as import_router
from .api_jobs import ctx_of, router as jobs_router
from .api_queue import router as queue_router  # очередь: порядок и время
from .api_link import router as link_router
from .api_lyrics import router as lyrics_router
from .api_settings import router as settings_router
from .api_songs import router as songs_router
from .api_tags import router as tags_router
from .api_targets import router as targets_router
from .api_usdb import router as usdb_router
from .context import ApiError, AppContext
from .params import defaults_payload

log = logging.getLogger("karaoke.web")
PURGE_EVERY_S = 6 * 3600
_HTTP_DETAILS = {404: "Не найдено", 405: "Метод не поддерживается", 413: "Слишком большой запрос"}


class BasicAuthMiddleware:
    """HTTP Basic по WEB_PASSWORD (логин любой) на всё: API, SSE, статику, документацию."""

    def __init__(self, app, expected: str):
        self.app = app
        self.expected = expected.encode("utf-8")

    def _ok(self, scope) -> bool:
        for name, value in scope.get("headers", []):
            if name == b"authorization" and value[:6].lower() == b"basic ":
                try:
                    _, _, given = base64.b64decode(value[6:].strip(), validate=True).partition(b":")
                except (binascii.Error, ValueError):
                    return False
                return secrets.compare_digest(given, self.expected)
        return False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.expected or self._ok(scope):
            return await self.app(scope, receive, send)
        body = json.dumps({"detail": "Нужен пароль"}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", b'Basic realm="karaoke", charset="UTF-8"')]})
        await send({"type": "http.response.body", "body": body})


def _cleanup(ctx: AppContext) -> None:
    """Очистка корзины по TRASH_DAYS и распаковок импорта старше часа."""
    try:
        removed = ctx.trash.purge()
        if removed:
            log.info("корзина: окончательно удалено записей: %s", removed)
    except Exception:  # noqa: BLE001 — сбой очистки не должен ронять веб
        log.exception("очистка корзины не удалась")
    try:
        purge_imports(ctx.paths)
    except Exception:  # noqa: BLE001
        log.exception("уборка imports/ не удалась")


async def _purge_loop(ctx: AppContext) -> None:
    """Уборка каждые 6 часов (первый проход — при старте, в lifespan)."""
    while True:
        await asyncio.sleep(PURGE_EVERY_S)
        await asyncio.to_thread(_cleanup, ctx)


def create_app(*, data_dir: str | Path | None = None, env: dict | None = None,
               storage_factory=None, trash=None, static_dir: str | Path | None = None,
               http=None, yandex_factory=None) -> FastAPI:
    env = dict(os.environ if env is None else env)
    ctx = AppContext(data_dir or env.get("DATA_DIR") or "/data", env=env,
                     storage_factory=storage_factory, trash=trash, http=http,
                     yandex_factory=yandex_factory)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx.migrate_targets()  # список хранилищ и корзина на их id — до первого запроса
        ctx.trash.purge()  # при старте — синхронно, до первого запроса
        purge_imports(ctx.paths)
        task = asyncio.create_task(_purge_loop(ctx))
        try:
            yield
        finally:
            task.cancel()
            ctx.reset_storage()

    app = FastAPI(title="karaoke-services", version=__version__, lifespan=lifespan,
                  description="REST API караоке-сервиса: задания UltraSinger, песни, корзина, настройки.",
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.ctx = ctx

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse({"detail": exc.detail, **exc.extra}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        names = [str(e.get("loc", ["?"])[-1]) for e in exc.errors()]
        return JSONResponse({"detail": f"Неверный запрос: проверьте поля {', '.join(names)}",
                             "field": names[0] if names else None}, status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) and not exc.detail.isascii() else \
            _HTTP_DETAILS.get(exc.status_code, "Ошибка запроса")
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.get("/api/status", tags=["Общее"], summary="GPU воркера, папка результата, версия")
    def status(request: Request):
        c = ctx_of(request)
        return {"gpu": c.gpu_status(), "output": c.output_status(), "version": __version__}

    @app.get("/api/defaults", tags=["Общее"], summary="Модели, языки и значения по умолчанию")
    def defaults(request: Request):
        return defaults_payload(ctx_of(request))

    app.include_router(import_router)  # раньше jobs: POST /api/jobs/import
    # library-tools 06: массовые действия — раньше jobs и songs (POST /api/jobs/instrumental/bulk)
    app.include_router(bulk_router)
    app.include_router(queue_router)  # раньше jobs: POST /api/jobs/schedule
    app.include_router(jobs_router)
    app.include_router(songs_router)
    app.include_router(tags_router)
    app.include_router(settings_router)
    app.include_router(targets_router)
    app.include_router(lyrics_router)
    app.include_router(usdb_router)
    app.include_router(link_router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
                   include_in_schema=False)
    def _api_404(rest: str):
        raise ApiError(404, "Не найдено")

    static = Path(static_dir or env.get("WEB_STATIC_DIR") or Path(__file__).resolve().parent.parent / "static")
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="static")

    app.add_middleware(BasicAuthMiddleware, expected=ctx.password)
    return app

