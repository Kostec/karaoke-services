"""Зеркала хранилищ (истории 44–48): «откуда → куда», вкл./выкл., «Синхронизировать сейчас».

Само зеркало синхронизирует воркер (задание ``mirror``, раз в 30 минут); здесь — настройки,
проверки пары и постановка задания по кнопке.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from karaoke_core.db import TARGET_NOT_FOUND, Job, Mirror

from .api_jobs import ctx_of
from .context import ApiError, AppContext, not_found

router = APIRouter(prefix="/api/mirrors", tags=["Зеркала"])

MIRROR_NOT_FOUND = "Зеркало не найдено"
MIRROR_SELF = "Хранилище не может быть зеркалом самого себя"
MIRROR_REVERSE = "Обратное зеркало уже есть"
MIRROR_DUPLICATE = "Такое зеркало уже есть"
MIRROR_BUSY = "Зеркало уже синхронизируется"
MIRROR_TARGET_GONE = "Хранилище зеркала удалено из настроек"
DELETED_NAME = "удалено из настроек"
WAIT_PREFIX = "Ждёт хранилище"


class MirrorIn(BaseModel):
    from_target: str = ""
    to_target: str = ""
    enabled: bool = True


class MirrorPatch(BaseModel):
    from_target: str | None = None
    to_target: str | None = None
    enabled: bool | None = None


def _name(ctx: AppContext, target_id: str) -> str | None:
    t = ctx.settings.get_target(target_id)
    return (t.name or t.label) if t is not None else None


def active_job(ctx: AppContext, mirror_id: str) -> Job | None:
    """Незавершённое задание ``mirror`` этого зеркала."""
    return next((j for j in ctx.jobs.active("mirror") if j.params.get("mirror_id") == mirror_id), None)


def _waiting(ctx: AppContext, m: Mirror, job: Job | None) -> str | None:
    """«Ждёт хранилище «X»» — у задания зеркала или у его копий, ждущих цель."""
    if job is not None and (job.stage or "").startswith(WAIT_PREFIX):
        return job.stage
    for copy in ctx.jobs.active("copy"):
        p = copy.params
        if (p.get("from_target"), p.get("to_target")) == (m.from_target, m.to_target) \
                and (copy.stage or "").startswith(WAIT_PREFIX):
            return copy.stage
    return None


def _out(ctx: AppContext, m: Mirror) -> dict:
    src, dst = _name(ctx, m.from_target), _name(ctx, m.to_target)
    job = active_job(ctx, m.id)
    return {**m.to_dict(), "from_name": src or DELETED_NAME, "to_name": dst or DELETED_NAME,
            "missing": src is None or dst is None, "job": job.to_dict() if job else None,
            "waiting": _waiting(ctx, m, job)}


def _get(ctx: AppContext, mirror_id: str) -> Mirror:
    m = next((x for x in ctx.settings.get_mirrors() if x.id == mirror_id), None)
    if m is None:
        raise not_found(MIRROR_NOT_FOUND)
    return m


def _check(ctx: AppContext, src: str, dst: str, own_id: str = "") -> None:
    """Проверки пары: оба хранилища есть, не на себя, нет обратного и такого же зеркала."""
    known = {t.id for t in ctx.settings.get_targets()}
    if src not in known:
        raise ApiError(400, TARGET_NOT_FOUND, field="from_target")
    if dst not in known:
        raise ApiError(400, TARGET_NOT_FOUND, field="to_target")
    if src == dst:
        raise ApiError(400, MIRROR_SELF, field="to_target")
    for other in ctx.settings.get_mirrors():
        if other.id == own_id:
            continue
        if (other.from_target, other.to_target) == (dst, src):
            raise ApiError(400, MIRROR_REVERSE, field="to_target")
        if (other.from_target, other.to_target) == (src, dst):
            raise ApiError(400, MIRROR_DUPLICATE, field="to_target")


def _save(ctx: AppContext, m: Mirror) -> Mirror:
    try:
        return ctx.settings.save_mirror(m)
    except ValueError as e:
        raise ApiError(400, str(e), field="to_target") from None


@router.get("", summary="Зеркала хранилищ")
def list_mirrors(request: Request):
    ctx = ctx_of(request)
    return {"mirrors": [_out(ctx, m) for m in ctx.settings.get_mirrors()]}


@router.post("", status_code=201, summary="Добавить зеркало")
def create_mirror(body: MirrorIn, request: Request):
    ctx = ctx_of(request)
    _check(ctx, body.from_target, body.to_target)
    return _out(ctx, _save(ctx, Mirror(from_target=body.from_target, to_target=body.to_target,
                                       enabled=body.enabled)))


@router.put("/{mirror_id}", summary="Изменить зеркало (вкл./выкл., откуда, куда)")
def update_mirror(mirror_id: str, body: MirrorPatch, request: Request):
    ctx = ctx_of(request)
    m = _get(ctx, mirror_id)
    src = body.from_target if body.from_target is not None else m.from_target
    dst = body.to_target if body.to_target is not None else m.to_target
    _check(ctx, src, dst, m.id)
    enabled = m.enabled if body.enabled is None else body.enabled
    return _out(ctx, _save(ctx, Mirror(id=m.id, from_target=src, to_target=dst, enabled=enabled)))


@router.delete("/{mirror_id}", summary="Убрать зеркало (песни не трогаются)")
def delete_mirror(mirror_id: str, request: Request):
    ctx = ctx_of(request)
    _get(ctx, mirror_id)
    ctx.settings.delete_mirror(mirror_id)
    return {"ok": True}


@router.post("/{mirror_id}/run", status_code=201, summary="Синхронизировать сейчас")
def run_mirror(mirror_id: str, request: Request):
    ctx = ctx_of(request)
    m = _get(ctx, mirror_id)
    src, dst = _name(ctx, m.from_target), _name(ctx, m.to_target)
    if src is None or dst is None:
        raise ApiError(409, MIRROR_TARGET_GONE)
    if active_job(ctx, m.id) is not None:
        raise ApiError(409, MIRROR_BUSY)
    return ctx.jobs.enqueue("mirror", {"artist": src, "title": dst}, {"mirror_id": m.id}).to_dict()
