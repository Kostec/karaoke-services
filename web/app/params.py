"""Параметры генерации: значения по умолчанию (из .env) и проверка присланных."""

from __future__ import annotations

import json

from karaoke_core import naming

from .context import ApiError, AppContext

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3"]
COMPUTE_TYPES = ["int8", "float32"]  # float16 на GTX 1080 (Pascal) не работает
DEMUCS_MODELS = ["htdemucs", "htdemucs_ft", "htdemucs_6s", "hdemucs_mmi", "mdx", "mdx_extra"]
LANGUAGES = [
    ("ru", "Русский"), ("en", "Английский"), ("uk", "Украинский"), ("be", "Белорусский"),
    ("de", "Немецкий"), ("fr", "Французский"), ("es", "Испанский"), ("it", "Итальянский"),
    ("pt", "Португальский"), ("pl", "Польский"), ("cs", "Чешский"), ("fi", "Финский"),
    ("sv", "Шведский"), ("tr", "Турецкий"), ("ja", "Японский"), ("ko", "Корейский"),
    ("zh", "Китайский"),
]

# Лимиты размеров (единственный источник; MAX_UPLOAD_MB для mp3 — из окружения).
MAX_COVER_MB = 10  # обложка из формы
MAX_LYRICS_MB = 1  # файл текста из формы
MAX_BULK_SONGS = 1000  # песен в одной массовой операции «Песен» (теги, удаление, минусовка)
MAX_ZIP_SONGS = 500  # песен в одном общем zip
DEFAULT_MAX_IMPORT_MB = 500  # лимит архива/файлов импорта, если MAX_IMPORT_MB не задан


def max_import_mb(ctx) -> int:
    return ctx.int_env("MAX_IMPORT_MB", DEFAULT_MAX_IMPORT_MB)
MAX_FOLDER_AUDIO_MB = 200  # mp3 чужой песни, копируемый из папки результата во вход задания
DEFAULT_MAX_VIDEO_MB = 2000  # лимит видеофайла, если MAX_VIDEO_MB не задан
VIDEO_HEIGHTS = [360, 480, 720, 1080, 0]  # качество видео по ссылке; 0 — лучшее
DEFAULT_VIDEO_HEIGHT = 720


def max_video_mb(ctx) -> int:
    return ctx.int_env("MAX_VIDEO_MB", DEFAULT_MAX_VIDEO_MB)


def align_models(ctx: AppContext) -> dict[str, str]:
    return {"ru": ctx.env.get("DEFAULT_ALIGN_MODEL_RU", "")}


def defaults(ctx: AppContext) -> dict:
    """Умолчания формы — только из окружения (.env → compose), литералов здесь нет."""
    env = ctx.env
    lang = env.get("DEFAULT_LANGUAGE", "")
    batch = str(env.get("DEFAULT_BATCH_SIZE", "")).strip()
    return {
        "whisper_model": env.get("DEFAULT_WHISPER_MODEL", ""),
        "language": lang,
        "compute_type": env.get("DEFAULT_COMPUTE_TYPE", ""),
        "batch_size": int(batch) if batch.isdigit() else None,
        "align_model": align_models(ctx).get(lang, ""),
        "vad_onset": None,
        "vad_offset": None,
        "demucs_model": DEMUCS_MODELS[0],
        "keep_debug": False,
        "lrc_timing": False,  # окна строк из LRC (--lyrics_timing), если строки совпали
    }


def defaults_payload(ctx: AppContext) -> dict:
    return {
        "whisper_models": WHISPER_MODELS,
        "compute_types": COMPUTE_TYPES,
        "demucs_models": DEMUCS_MODELS,
        "languages": [{"code": c, "name": n} for c, n in LANGUAGES],
        "align_models": align_models(ctx),
        "defaults": defaults(ctx),
        "max_upload_mb": ctx.max_upload_mb,
        "max_cover_mb": MAX_COVER_MB,
        "max_lyrics_mb": MAX_LYRICS_MB,
        "max_import_mb": max_import_mb(ctx),
        "max_video_mb": max_video_mb(ctx),
        "video_heights": VIDEO_HEIGHTS,
        "default_video_height": DEFAULT_VIDEO_HEIGHT,
        "video_exts": list(naming.VIDEO_EXT_ORDER),
        "trash_days": ctx.trash.days,
    }


def _vad(value, name: str):
    if value in (None, ""):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name}: нужно число от 0 до 1", field=name) from None
    if not 0 <= v <= 1:
        raise ApiError(400, f"{name}: нужно число от 0 до 1", field=name)
    return v


def parse_params(ctx: AppContext, raw: str | dict | None) -> dict:
    """Слить присланные параметры с умолчаниями и проверить. Ошибка → ApiError(400)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raw = None
    if not isinstance(raw, dict):
        raise ApiError(400, "Параметры должны быть JSON-объектом", field="params")
    base = defaults(ctx)
    p = {**base, **{k: v for k, v in raw.items() if k in base}}
    if p["whisper_model"] not in WHISPER_MODELS:
        raise ApiError(400, "Неизвестная модель Whisper: " + str(p["whisper_model"]), field="whisper_model")
    if p["compute_type"] not in COMPUTE_TYPES:
        raise ApiError(400, "Тип вычислений: только int8 или float32 (float16 GTX 1080 не поддерживает)", field="compute_type")
    try:
        p["batch_size"] = int(p["batch_size"])
    except (TypeError, ValueError):
        p["batch_size"] = 0
    if not 1 <= p["batch_size"] <= 64:
        raise ApiError(400, "Batch size: целое число от 1 до 64", field="batch_size")
    lang = str(p["language"] or "").strip().lower()
    if not lang or len(lang) > 10 or not lang.replace("-", "").isalpha():
        raise ApiError(400, "Укажите язык песни", field="language")
    p["language"] = lang
    if "align_model" not in raw:
        p["align_model"] = align_models(ctx).get(lang, "")
    p["align_model"] = str(p["align_model"] or "").strip()
    p["vad_onset"] = _vad(p["vad_onset"], "vad_onset")
    p["vad_offset"] = _vad(p["vad_offset"], "vad_offset")
    if p["demucs_model"] not in DEMUCS_MODELS:
        raise ApiError(400, "Неизвестная модель Demucs: " + str(p["demucs_model"]), field="demucs_model")
    p["keep_debug"] = bool(p["keep_debug"])
    p["lrc_timing"] = bool(p["lrc_timing"])
    return p
