"""Свои теги пользователя: REST тегов и набор тегов песни (по ключу «исполнитель — название»)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from karaoke_core.db import DEFAULT_TAG_COLOR, TAG_COLORS, Tag, TagError
from karaoke_core.naming import song_tag_key

from .api_jobs import ctx_of
from .context import ApiError, AppContext, not_found

router = APIRouter(prefix="/api", tags=["Теги"])

TAG_NOT_FOUND = "Тег не найден"


class TagIn(BaseModel):
    name: str = ""
    color: str | None = None


class TagPatch(BaseModel):
    name: str | None = None
    color: str | None = None


class SongTagsIn(BaseModel):
    tag_ids: list[str] = []


def _out(tag: Tag, count: int) -> dict:
    return {**tag.to_dict(), "count": count}


def _count(ctx: AppContext, tag_id: str) -> int:
    return ctx.tags.counts().get(tag_id, 0)


def _tag_error(e: TagError) -> ApiError:
    return ApiError(400, str(e), field=e.field)


@router.get("/tags", summary="Свои теги, палитра и цвет по умолчанию")
def list_tags(request: Request):
    tags = ctx_of(request).tags
    counts = tags.counts()
    return {"tags": [_out(t, counts.get(t.id, 0)) for t in tags.list()],
            "colors": list(TAG_COLORS), "default_color": DEFAULT_TAG_COLOR}


@router.post("/tags", status_code=201, summary="Создать тег")
def create_tag(body: TagIn, request: Request):
    # Поле не прислано (старый фронт) — цвет по умолчанию; прислано ""/null/чужое — 400 у поля color.
    color = body.color if "color" in body.model_fields_set else DEFAULT_TAG_COLOR
    try:
        tag = ctx_of(request).tags.create(body.name, color)
    except TagError as e:
        raise _tag_error(e) from None
    return _out(tag, 0)


@router.put("/tags/{tag_id}", summary="Переименовать тег или сменить цвет")
def update_tag(tag_id: str, body: TagPatch, request: Request):
    ctx = ctx_of(request)
    try:
        tag = ctx.tags.update(tag_id, name=body.name, color=body.color)
    except KeyError:
        raise not_found(TAG_NOT_FOUND) from None
    except TagError as e:
        raise _tag_error(e) from None
    return _out(tag, _count(ctx, tag.id))


@router.delete("/tags/{tag_id}", summary="Удалить тег (снимается со всех песен)")
def delete_tag(tag_id: str, request: Request):
    try:
        removed = ctx_of(request).tags.delete(tag_id)
    except KeyError:
        raise not_found(TAG_NOT_FOUND) from None
    return {"ok": True, "removed": removed}


@router.put("/songs/{song_id}/tags", tags=["Песни"], summary="Набор своих тегов песни (у всех её копий)")
def set_song_tags(song_id: str, body: SongTagsIn, request: Request):
    ctx = ctx_of(request)
    item = ctx.find_song(song_id)
    try:
        ids = ctx.tags.set_for_song(song_tag_key(item.artist, item.title), body.tag_ids)
    except KeyError:
        raise ApiError(400, "Такого тега нет — обновите страницу", field="tag_ids") from None
    return {"tags": ids}
