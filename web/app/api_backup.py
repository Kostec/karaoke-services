"""Резервная копия настроек (истории 66–68): скачать одним JSON-файлом без паролей и токенов,
загрузить обратно — сначала план (``apply=0``), потом применение (``apply=1``).

Сборка и разбор файла — ``karaoke_core.backup``; здесь только HTTP.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from karaoke_core import backup

from .api_jobs import ctx_of
from .context import ApiError

router = APIRouter(prefix="/api/settings/backup", tags=["Настройки"])

# Файл настроек — килобайты; больше — точно не он.
MAX_BACKUP_BYTES = 5 * 1024 * 1024


@router.get("", summary="Скачать настройки одним файлом (без паролей и токенов)")
def download_backup(request: Request):
    ctx = ctx_of(request)
    data = backup.export_settings(ctx.settings, ctx.tags)
    name = f"karaoke-settings-{dt.date.today().isoformat()}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                       "Cache-Control": "no-store"})


@router.post("", summary="Загрузить файл настроек: apply=0 — только план, apply=1 — применить")
def upload_backup(request: Request, apply: int = Query(0, ge=0, le=1),
                  file: UploadFile | None = File(None)):
    ctx = ctx_of(request)
    if file is None:
        raise ApiError(400, backup.NOT_SETTINGS, field="file")
    raw = file.file.read(MAX_BACKUP_BYTES + 1)
    try:
        if len(raw) > MAX_BACKUP_BYTES:
            raise backup.BackupError()
        plan = backup.plan_import(backup.read_backup(raw), ctx.settings, ctx.tags)
    except backup.BackupError as e:
        raise ApiError(400, str(e), field="file") from None
    if apply:
        try:
            backup.apply_import(plan, ctx.settings, ctx.tags)
        except ValueError as e:  # TagError, TARGET_NOT_FOUND: гонка с правкой настроек в другой вкладке
            raise ApiError(409, f"Не удалось применить: {e}") from None
        for t in plan.changed_targets:
            ctx.reset_storage(t.id)  # адрес мог смениться — открыть заново
    return plan.to_dict()
