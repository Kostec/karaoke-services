"""Настройки папки результата. Пароль Samba API никогда не возвращает."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel

from karaoke_core.db import OutputTarget
from karaoke_core.storage import StorageError

from .api_jobs import ctx_of
from .context import ApiError, AppContext


class OutputIn(BaseModel):
    kind: str = "smb"
    host: str = ""
    share: str = ""
    path: str = ""
    user: str = ""
    password: str | None = None  # пусто или нет поля — «не менять»


router = APIRouter(prefix="/api/settings", tags=["Настройки"])


def _target(ctx: AppContext, body: OutputIn) -> OutputTarget:
    kind = body.kind.strip().lower()
    if kind not in ("smb", "local"):
        raise ApiError(400, "Тип папки результата: smb или local", field="kind")
    path = body.path.strip().replace("\\", "/").strip("/")
    if any(part in ("..", ".") for part in path.split("/")) or ":" in path:
        raise ApiError(400, "Недопустимый путь", field="path")
    fields = {"kind": kind, "path": path, "host": body.host.strip(), "share": body.share.strip().strip("/"),
              "user": body.user.strip()}
    if kind == "smb" and (not fields["host"] or not fields["share"]):
        raise ApiError(400, "Укажите адрес сервера и имя шары",
                       field="host" if not fields["host"] else "share")
    # Пустой пароль = «не менять» — только для той же учётки на том же сервере;
    # иначе прежний пароль ушёл бы на чужой хост.
    current = ctx.target()
    same = (current.kind, current.host, current.share, current.user) ==         (kind, fields["host"], fields["share"], fields["user"])
    if body.password:
        fields["password"] = body.password
    elif kind == "smb" and same:
        fields["password"] = current.password
    elif kind == "smb" and fields["user"]:
        raise ApiError(400, "Введите пароль: сервер, шара или логин изменились", field="password")
    else:
        fields["password"] = ""  # гостевой доступ или локальная папка
    return OutputTarget(**fields)


def _probe(ctx: AppContext, target: OutputTarget) -> None:
    try:
        storage = ctx.storage_factory(target)
    except StorageError as e:
        raise ApiError(400, f"Папка результата недоступна: {e}") from None
    try:
        storage.probe()
    except StorageError as e:
        raise ApiError(400, f"Папка результата недоступна: {e}") from None
    finally:
        try:
            storage.close()
        except Exception:
            pass


def _public(ctx: AppContext, target: OutputTarget) -> dict:
    return {**target.public(), "local_root_host": ctx.env.get("LOCAL_OUTPUT_ROOT", "")}


@router.get("/output", summary="Текущая папка результата (без пароля)")
def get_output(request: Request):
    ctx = ctx_of(request)
    return _public(ctx, ctx.target())


@router.put("/output", summary="Сохранить папку результата (только проверенную)")
def put_output(body: OutputIn, request: Request, background: BackgroundTasks):
    ctx = ctx_of(request)
    target = _target(ctx, body)
    _probe(ctx, target)
    saved = ctx.settings.set_output(target)
    ctx.reset_storage()
    background.add_task(ctx.rescan)
    return _public(ctx, saved)


@router.post("/output/test", summary="Проверить цель: записать и удалить пробный файл")
def test_output(body: OutputIn, request: Request):
    ctx = ctx_of(request)
    target = _target(ctx, body)
    _probe(ctx, target)
    return {"ok": True, "label": target.label}
