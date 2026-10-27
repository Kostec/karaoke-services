"""Очередь: порядок ожидающих заданий и отложенный запуск (истории 56-58)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from karaoke_core.db import BAD_TIME, MOVE_NOT_QUEUED, SCHEDULE_NOT_QUEUED

from .api_jobs import ctx_of
from .context import ApiError

router = APIRouter(prefix="/api/jobs", tags=["Очередь"])


class MoveIn(BaseModel):
    where: Literal["up", "down", "first"]


class ScheduleIn(BaseModel):
    start_at: str | None = None


def _checked_time(value: str | None) -> str | None:
    """Время обязано быть с поясом (``…Z``): без него сервер счёл бы его UTC и сдвинул запуск."""
    if value is None or not str(value).strip():
        return None
    try:
        at = datetime.fromisoformat(str(value).strip())
    except ValueError:
        raise ApiError(400, BAD_TIME, field="start_at") from None
    if at.tzinfo is None:
        raise ApiError(400, BAD_TIME, field="start_at")
    return str(value).strip()


def _failure(e: ValueError) -> ApiError:
    msg = str(e)
    if msg in (MOVE_NOT_QUEUED, SCHEDULE_NOT_QUEUED):
        return ApiError(409, msg)
    return ApiError(400, msg, field="start_at")


@router.post("/schedule", summary="Отложить все ожидающие без своего времени")
def schedule_all(body: ScheduleIn, request: Request):
    at = _checked_time(body.start_at)
    if at is None:
        raise ApiError(400, BAD_TIME, field="start_at")
    try:
        return {"count": ctx_of(request).jobs.schedule_all(at)}
    except ValueError as e:
        raise _failure(e) from None


@router.post("/{job_id}/move", summary="Переставить ожидающее задание")
def move(job_id: int, body: MoveIn, request: Request):
    jobs = ctx_of(request).jobs
    if jobs.get(job_id) is None:
        raise ApiError(404, "Задание не найдено")
    try:
        return {"jobs": [j.to_dict() for j in jobs.move(job_id, body.where)]}
    except ValueError as e:
        raise _failure(e) from None


@router.post("/{job_id}/schedule", summary="Отложить задание до времени или запустить сейчас")
def schedule(job_id: int, body: ScheduleIn, request: Request):
    jobs = ctx_of(request).jobs
    if jobs.get(job_id) is None:
        raise ApiError(404, "Задание не найдено")
    at = _checked_time(body.start_at)
    try:
        return jobs.schedule(job_id, at).to_dict()
    except ValueError as e:
        raise _failure(e) from None
