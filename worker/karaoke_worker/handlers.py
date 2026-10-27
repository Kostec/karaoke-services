"""Обработчики заданий: generate, instrumental, publish (Решения §2–§6, истории 30–33, 43–47)."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol

from karaoke_core import linealign, musiclink, naming, postprocess, ultrastar
from karaoke_core.db import FINAL_STATES, LOCAL_TARGET_ID, Job, instrumental_params, now, song_id_for
from karaoke_core.paths import INPUT_AUDIO, INPUT_COVER_STEM, INPUT_PARAMS, INPUT_VIDEO_STEM
from karaoke_core.storage import Storage, StorageError, StorageNotFound
from karaoke_core.trash import TrashError

from .base import _NETWORK_MARKERS, JobContext, JobFailed, remove_tree
from .progress import (IMPORT_PREPARE, PUBLISH, STAGE_DOWNLOAD, STAGE_POSTPROCESS, STAGE_PREPARE,
                       STAGE_COPY, STAGE_COPY_DOWNLOAD, STAGE_RENAME, STAGE_VIDEO_DOWNLOAD, DownloadTracker, ProgressTracker)

__all__ = ["Handler", "GenerateHandler", "InstrumentalHandler", "ImportHandler", "PublishHandler",
           "VideoHandler", "CopyHandler", "RenameHandler", "COPY_RETRY_S", "download_song_dir", "wait_retry",
           "rename_txt", "download_video", "publish_video", "INPUT_VIDEO_STEM",
           "HANDLERS", "prepare_lyrics", "align_lines", "ultrasinger_args", "parse_lrc", "lyrics_lines", "lrc_matches", "audio_only_copy", "to_mp3",
           "download_youtube", "download_link", "download_song_youtube", "search_youtube",
           "rank_search_results", "song_end_ms"]



class Handler(Protocol):
    needs_gpu: bool

    def run(self, job: Job, ctx: JobContext) -> None: ...


def prepare_lyrics(text: str) -> str:
    """Текст для ``--lyrics``: без BOM, переводы строк LF. Позже — раскрытие [Припев] (R29)."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return text.strip("\n") + "\n" if text.strip() else ""


# ---------------------------------------------------------------------------- тайминги LRC
# Повтор один в один lrc_timing.parse_lrc / match_lrc_lines и lyrics_alignment.read_lyrics /
# _norm_words форка UltraSinger (--lyrics_timing): ответ «совпало» здесь и там должен быть одним.

LRC_NOT_USED = "Тайминги LRC не использованы: текст отличается"
_LRC_TIME_TAG = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_LRC_OFFSET = re.compile(r"^\s*\[offset:\s*([+-]?\d+)\s*\]\s*$", re.IGNORECASE)
_TAG_ONLY_LINE = re.compile(r"^\s*\[[^\]]*\]\s*$")  # [Chorus], [Припев]
_LYRICS_TIME_TAG = re.compile(r"\[\d{1,2}:\d{2}(\.\d+)?\]")


def _norm_line(text: str) -> str:
    """Ключ строки: слова в нижнем регистре, ё→е, без знаков (не буква/цифра/_), через один пробел."""
    words = (re.sub(r"[^\w]", "", w.lower().replace("ё", "е")) for w in (text or "").split())
    return " ".join(w for w in words if w)


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """LRC → [(секунды, строка)] по времени; строка с N метками даёт N записей; [offset:±мс]."""
    offset, entries = 0.0, []
    for raw in (text or "").lstrip("﻿").splitlines():
        m = _LRC_OFFSET.match(raw)
        if m:
            offset = int(m.group(1)) / 1000
            continue
        line, times = raw.strip(), []
        while m := _LRC_TIME_TAG.match(line):
            value = int(m.group(1)) * 60 + int(m.group(2))
            if m.group(3):
                value += int(m.group(3)) / (10 ** len(m.group(3)))
            times.append(value)
            line = line[m.end():].lstrip()
        if not times:
            continue  # метаданные или строка без метки
        line = re.sub(r"\s+", " ", line).strip()
        entries += [(t, line) for t in times]
    entries = [(round(max(t - offset, 0.0), 3), line) for t, line in entries]
    entries.sort(key=lambda e: e[0])
    return entries


def lyrics_lines(text: str) -> list[str]:
    """Строки текста так, как их читает UltraSinger: без меток, без [Припев] и пустых."""
    out = []
    for line in (text or "").lstrip("﻿").splitlines():
        line = _LYRICS_TIME_TAG.sub("", line)
        line = _TAG_ONLY_LINE.sub("", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and _norm_line(line):
            out.append(line)
    return out


def lrc_matches(lyrics_text: str, lrc_text: str) -> bool:
    """Совпадают ли строки текста со строками LRC (всё или ничего, как в форке)."""
    lines = lyrics_lines(lyrics_text)
    sung = [line for _, line in parse_lrc(lrc_text) if not _TAG_ONLY_LINE.match(line) and _norm_line(line)]
    return bool(lines) and len(sung) == len(lines) and all(
        _norm_line(a) == _norm_line(b) for a, b in zip(sung, lines))


def ultrasinger_args(params: dict, in_mp3: Path, out_dir: Path, lyrics: Path | None,
                     env: dict | None = None, *, lyrics_timing: Path | None = None) -> list[str]:
    """Аргументы UltraSinger (Решения §4). ``--interactive`` не передаётся никогда."""
    env = env or {}

    def get(key: str, env_key: str | None = None):
        value = params.get(key)
        if value in (None, "") and env_key:
            value = env.get(env_key)
        return value

    args = ["-i", str(in_mp3), "-o", str(out_dir)]
    for flag, key, env_key in (("--whisper", "whisper_model", "DEFAULT_WHISPER_MODEL"),
                               ("--whisper_compute_type", "compute_type", "DEFAULT_COMPUTE_TYPE"),
                               ("--whisper_batch_size", "batch_size", "DEFAULT_BATCH_SIZE"),
                               ("--language", "language", "DEFAULT_LANGUAGE"),
                               ("--whisper_align_model", "align_model", None)):
        value = get(key, env_key)
        if value not in (None, ""):
            args += [flag, str(value)]
    if lyrics is not None:
        args += ["--lyrics", str(lyrics)]
        if lyrics_timing is not None:
            args += ["--lyrics_timing", str(lyrics_timing)]
    for key in ("vad_onset", "vad_offset"):
        if params.get(key) is not None:
            args += [f"--{key}", str(params[key])]
    if params.get("demucs_model"):
        args += ["--demucs", str(params["demucs_model"])]
    if params.get("keep_debug"):
        args += ["--keep_cache"]  # lyrics_debug.json лежит в cache/
    return args + ["--format_version", postprocess.FORMAT_VERSION]


AUDIO_ONLY_MESSAGE = ("Не удалось прочитать звук из mp3 — файл повреждён или это не mp3; "
                      "загрузите другой файл")


def audio_only_copy(ctx: JobContext, job_id: int, src: Path, dest: Path) -> None:
    """Копия mp3 только с первым аудиопотоком, без перекодирования. Обложка в тегах (ID3 APIC)
    для ffmpeg — видеопоток «attached pic», и UltraSinger принимает такой mp3 за видео."""
    try:
        ctx.run_command(job_id, ctx.ffmpeg_cmd() + [
            "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(src),
            "-map", "0:a:0", "-c:a", "copy", "-map_metadata", "0", str(dest)], what="ffmpeg")
    except JobFailed as e:
        tail = e.user_message.partition("\n\n")[2]  # «Последние строки лога: …»
        raise JobFailed("input", f"{AUDIO_ONLY_MESSAGE}\n\n{tail}" if tail else AUDIO_ONLY_MESSAGE) from None
    if not dest.is_file():
        raise JobFailed("input", AUDIO_ONLY_MESSAGE)


def _storage(ctx: JobContext, target_id: str | None = None) -> Storage:
    """Хранилище по id (``None`` — основная цель); недоступно — ``JobFailed("storage")``."""
    try:
        return ctx.storage(target_id)
    except StorageError as e:
        _reset(ctx, target_id)
        raise JobFailed("storage", f"Папка результата недоступна: {e}") from None


def _reset(ctx: JobContext, target_id: str | None) -> None:
    """Сбросить только упавшее хранилище (``None`` — основная цель); прочие остаются открытыми."""
    try:
        tid = ctx.target_of(target_id).id
    except StorageError:
        return  # хранилища нет в настройках — сбрасывать нечего
    ctx.reset_storage(tid)


def _start_publish(ctx: JobContext, job: Job) -> None:
    ctx.check_cancel(job.id, force=True)
    ctx.jobs.update(job.id, state="publishing", stage=PUBLISH[0], percent=PUBLISH[1])
    ctx.log(job.id, "Выкладка в папку результата…")


def _publish_error(ctx: JobContext, e: Exception, note: str = "", *,
                   target_id: str | None = None) -> JobFailed:
    _reset(ctx, target_id)
    return JobFailed("publish", f"ошибка выкладки: {e}{note}")


def _index(ctx: JobContext, job: Job, storage: Storage, rel_dir: str, own_song_id: str | None,
           removed: str | None = None) -> None:
    """Точечное обновление индекса песен; сбой индекса не роняет выложенную песню."""
    try:
        entry = storage.read_song(rel_dir)
        if entry is not None:
            if own_song_id is None:
                old = ctx.library.get(storage.target_id, rel_dir)
                own_song_id = old.own_song_id if old else None
            ctx.library.upsert(entry.to_library_item(storage.target_id, own_song_id=own_song_id,
                                                     scanned_at=now()))
        if removed and removed != rel_dir:
            ctx.library.remove(storage.target_id, removed)
    except Exception as e:  # noqa: BLE001 — индекс пересоберёт «Обновить»
        ctx.log(job.id, f"Предупреждение: индекс песен не обновлён: {e}")


def _done(ctx: JobContext, job: Job) -> None:
    ctx.jobs.update(job.id, state="done", percent=100)
    ctx.log(job.id, "Готово.")


# ============================================================================ generate

def _song_rel_dir(job: Job) -> str:
    return job.params.get("rel_dir") or naming.song_dir(job.artist, job.title)


def _save_sources(ctx: JobContext, job: Job, src: Job, rel_dir: str, replaced: str | None) -> str | None:
    """in/ задания → source/ (+ params.json); запись «своей» песни в БД. Возвращает её id."""
    params = {k: v for k, v in src.params.items() if k != "inputs"}
    params.update(artist=src.artist, title=src.title)
    video_url = (src.params.get("video") or {}).get("url") or src.params.get("video_url")
    if video_url:
        params["video_url"] = video_url  # по ней перезапуск или перегенерация скачают видео заново
    try:
        inputs = src.params.get("inputs") or {}
        in_dir = ctx.paths.abs(inputs["dir"]) if inputs.get("dir") else ctx.paths.job_in(_song_rel_dir(src), src.id)
        source = ctx.paths.source(rel_dir)
        tmp = source.with_name("source.new")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        if in_dir.is_dir():
            for f in in_dir.iterdir():
                if f.is_file() and not _is_input_video(f):  # видео уже в папке результата
                    shutil.copy2(f, tmp / f.name)
        (tmp / INPUT_PARAMS).write_text(json.dumps(params, ensure_ascii=False, indent=1), "utf-8")
        shutil.rmtree(source, ignore_errors=True)
        tmp.rename(source)
        own = ctx.songs.upsert(artist=src.artist, title=src.title, rel_dir=rel_dir, params=params)
        if replaced and replaced != rel_dir:
            old = ctx.songs.by_rel_dir(replaced)
            if old is not None:
                ctx.songs.delete(old.id)
        return own.id
    except Exception as e:  # noqa: BLE001 — песня уже выложена
        ctx.log(job.id, f"Предупреждение: исходники не сохранены: {e}")
        return None


def _is_input_video(f: Path) -> bool:
    return f.stem == INPUT_VIDEO_STEM and f.suffix.lower() in naming.VIDEO_EXTS


def _set_videogap(data: bytes, gap: str | None) -> bytes:
    """``#VIDEOGAP:gap`` или удаление строки (``gap`` None); прочие байты не меняются."""
    if gap is not None:
        return ultrastar.set_header_line(data, "VIDEOGAP", gap)
    song = ultrastar.parse(data)
    return ultrastar.render(song) if song.remove_header("VIDEOGAP") else data


def _carry_video(ctx: JobContext, job: Job, storage: Storage, old_rel: str, result: Path) -> None:
    """История 23: у заменяемой песни было видео, а в новом результате своего нет — файл
    переносится в result/ (пока старая папка не ушла в корзину), заголовки — под новое имя.
    Сбой — только предупреждение: песня важнее видео."""
    txts = sorted(f for f in result.iterdir() if f.is_file() and f.suffix.lower() == ".txt")
    if not txts:
        return
    txt = txts[0]
    data = txt.read_bytes()
    own = naming.video_file_name(ultrastar.parse(data).header("VIDEO"))
    if own and (result / own).is_file():
        return  # своё видео нового результата побеждает (история 30)
    part = None
    try:
        old = storage.read_song(old_rel)
        if old is None or not old.video:
            return
        old_song = ultrastar.parse(storage.read(f"{old_rel}/{old.txt_name}"))
        name = txt.stem + naming.video_suffix(PurePosixPath(old.video).suffix)
        data = ultrastar.set_header_line(data, "VIDEO", name)
        data = _set_videogap(data, postprocess.format_videogap(
            ultrastar.number(old_song.header("VIDEOGAP"), None)))
        part = result / f".{name}.part"
        with storage.open_read(f"{old_rel}/{old.video}") as f, open(part, "wb") as g:
            shutil.copyfileobj(f, g, 1024 * 1024)
        os.replace(part, result / name)
        txt.write_bytes(data)
        ctx.log(job.id, f"Видео прежней версии перенесено: {name}")
    except (StorageError, OSError, ValueError) as e:
        if part is not None:
            part.unlink(missing_ok=True)
        ctx.log(job.id, f"Предупреждение: видео прежней версии не перенесено: {e}")


class _PublishFailed(Exception):
    """Выкладка в одно хранилище не удалась (текст — причина и судьба прежней версии)."""


def _publish_into(ctx: JobContext, job: Job, storage: Storage, rel_dir: str, result: Path,
                  replaced: str | None) -> bool:
    """Выкладка ``result`` в одно хранилище по прежним правилам замены (истории 23, 34).
    Возвращает «прежняя версия ``replaced`` ушла из этого хранилища в корзину»."""
    item = None
    try:
        old_here = bool(replaced) and storage.exists(replaced)
        if old_here:
            _carry_video(ctx, job, storage, replaced, result)
        if old_here and replaced == rel_dir:
            # та же папка: старая версия — в корзину, при сбое выкладки — обратно
            item = ctx.trash.move_to_trash(storage, replaced, reason="заменена новой версией")
            ctx.log(job.id, f"Прежняя версия «{replaced}» перенесена в корзину ({item.id}).")
        written = storage.upload_dir(result, rel_dir)
    except (StorageError, TrashError, OSError) as e:
        note = ""
        if item is not None:
            try:
                if storage.exists(rel_dir):
                    storage.delete_dir(rel_dir)
                ctx.trash.restore(storage, item.id)
                note = "; прежняя версия возвращена на место"
            except (StorageError, TrashError, OSError) as e2:
                note = f"; прежняя версия осталась в корзине ({e2})"
        raise _PublishFailed(f"{e}{note}") from None
    ctx.log(job.id, f"Выложено в «{storage.label}»: {rel_dir} ({len(written)} файлов).")
    if not old_here:
        return False
    if replaced == rel_dir:
        return True
    # другая папка: сначала выложена новая, теперь старая — в корзину
    try:
        item = ctx.trash.move_to_trash(storage, replaced, reason="заменена новой версией")
        ctx.log(job.id, f"Прежняя версия «{replaced}» перенесена в корзину ({item.id}).")
        return True
    except (StorageError, TrashError, OSError) as e:
        ctx.log(job.id, f"Предупреждение: прежняя версия «{replaced}» не перенесена в корзину: {e}")
        return False


def _target_name(ctx: JobContext, target_id: str | None) -> str:
    """Имя хранилища для сообщений (удалённое из настроек — его id)."""
    try:
        target = ctx.target_of(target_id)
    except StorageError:
        return str(target_id or "")
    return target.name or target.label


def _publish_ids(ctx: JobContext, p: dict, replaced: str | None) -> list[str]:
    """Куда выкладывать новую песню (Решения §8): локальное, основная цель, а при замене —
    ещё и хранилище заменяемой песни (история 38)."""
    ids = [LOCAL_TARGET_ID]
    default = ctx.settings.get_default_target_id()
    if default not in ids:
        ids.append(default)
    if replaced:
        try:
            own = ctx.target_of(p.get("target_id")).id
        except StorageError:
            own = None  # хранилище заменяемой песни удалено из настроек
        if own and own not in ids:
            ids.append(own)
    return ids


def publish_song(ctx: JobContext, job: Job, src: Job) -> None:
    """Выложить результат generate-задания ``src`` (оно же ``job`` или источник «Выложить повторно»):
    сначала в локальное хранилище, затем в основную цель (Решения §8)."""
    rel_dir = _song_rel_dir(src)
    job_dir = ctx.paths.job(rel_dir, src.id)
    result = job_dir / "result"
    if not result.is_dir():
        raise JobFailed("publish", "ошибка выкладки: результат задания не найден в томе")
    _start_publish(ctx, job)
    p = src.params
    replaced = p.get("replace_rel_dir") if p.get("replace") else None
    default = ctx.settings.get_default_target_id()
    ids = _publish_ids(ctx, p, replaced)
    published: dict[str, tuple[Storage, bool]] = {}  # id хранилища → (Storage, прежняя ушла в корзину)
    for tid in ids:
        try:
            try:
                storage = ctx.storage(tid)
            except StorageError as e:
                raise _PublishFailed(str(e)) from None
            published[tid] = (storage, _publish_into(ctx, job, storage, rel_dir, result, replaced))
        except _PublishFailed as e:
            _reset(ctx, tid)
            if tid == LOCAL_TARGET_ID:
                raise JobFailed("publish", f"ошибка выкладки: {e}") from None
            name = _target_name(ctx, tid)
            what = f"Основная цель «{name}» недоступна" if tid == default else f"Хранилище «{name}» недоступно"
            ctx.log(job.id, f"{what}: {e}; песня сохранена в локальном хранилище и докопируется, "
                            "когда цель станет доступна")
    debug = job_dir / "debug"
    if debug.is_dir():  # отладка выравнивания — в папку песни тома (Решения §3)
        dest = ctx.paths.song_at(rel_dir) / "debug"
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(debug), str(dest))
    gone = replaced if any(removed for _, removed in published.values()) else None
    own_id = _save_sources(ctx, job, src, rel_dir, gone)
    for storage, removed in published.values():
        _index(ctx, job, storage, rel_dir, own_id, removed=replaced if removed else None)
    remove_tree(job_dir)
    local = published[LOCAL_TARGET_ID][0]
    inst = None
    if src.type == "import" and src.params.get("instrumental"):
        # минусовка (demucs — один раз) делается в локальном хранилище, остальным её привозит
        # «Копирование» с заменой после её окончания (R12: всегда локально + цель)
        inst = _enqueue_instrumental(ctx, job, src, local, rel_dir)
    for tid in ids:
        if tid == LOCAL_TARGET_ID or (tid in published and inst is None):
            continue
        late = tid not in published  # цель была недоступна — песня докопируется целиком
        _enqueue_copy_from_local(ctx, job, src, local, rel_dir, tid,
                                 replace=bool(p.get("replace")) if late else True,
                                 replace_rel_dir=replaced if late else None,
                                 after_job=inst.id if inst else None)
    _done(ctx, job)


def _enqueue_copy_from_local(ctx: JobContext, job: Job, src: Job, local: Storage, rel_dir: str, to: str, *,
                             replace: bool, replace_rel_dir: str | None, after_job: int | None) -> None:
    """Копирование песни из локального хранилища в ``to`` с ожиданием цели; сбой — предупреждение."""
    try:
        entry = local.read_song(rel_dir)
        copy = ctx.jobs.enqueue_copy(
            {"artist": src.artist, "title": src.title, "song_id": song_id_for(local.target_id, rel_dir)},
            rel_dir=rel_dir, txt_name=entry.txt_name if entry else "", from_target=local.target_id,
            to_target=to, replace=replace, wait=True, replace_rel_dir=replace_rel_dir,
            after_job=after_job, parent_id=job.id)
        ctx.log(job.id, f"Поставлено задание копирования в «{_target_name(ctx, to)}» #{copy.id}.")
    except Exception as e:  # noqa: BLE001 — песня уже выложена локально
        ctx.log(job.id, f"Предупреждение: копирование в «{_target_name(ctx, to)}» не поставлено: {e}")


def align_lines(ctx: JobContext, job_id: int, out_dir: Path, lyrics: str) -> None:
    """Границы строк выхода UltraSinger — по строкам текста пользователя (на месте).

    UltraSinger режет строки по паузам; здесь они ставятся по тексту (``linealign``).
    Сбой не валит задание: строка в лог, песня остаётся как есть.
    """
    try:
        txt = postprocess.find_song_txt(out_dir)
        raw = txt.read_bytes()
        song = ultrastar.parse(raw)
        result = linealign.align_song(song, lyrics)
        if result.total and result.unmatched < result.total:
            data = ultrastar.render(song)
            if data != raw:
                txt.write_bytes(data)
    except Exception as e:  # noqa: BLE001 — выравнивание необязательно, задание не валим
        ctx.log(job_id, f"Строки не выровнены по тексту: {e}" if isinstance(e, (postprocess.FinalizeError, ValueError))
                else f"Строки не выровнены по тексту: {type(e).__name__}: {e}")
        return
    if not result.total:
        ctx.log(job_id, "Строки не выровнены по тексту: в тексте нет слов")
    elif result.unmatched == result.total:
        ctx.log(job_id, "Строки не выровнены по тексту: ни одна строка текста не найдена в нотах")
    else:
        ctx.log(job_id, f"Строки выровнены по тексту: {result.total - result.unmatched} из {result.total}")


class GenerateHandler:
    needs_gpu = True

    def run(self, job: Job, ctx: JobContext) -> None:
        p = job.params
        rel_dir = _song_rel_dir(job)
        job_dir = ctx.paths.job(rel_dir, job.id)
        inputs = p.get("inputs") or {}
        in_dir = ctx.paths.abs(inputs["dir"]) if inputs.get("dir") else ctx.paths.job_in(rel_dir, job.id)
        audio = ctx.paths.abs(inputs["audio"]) if inputs.get("audio") else in_dir / INPUT_AUDIO
        cover = ctx.paths.abs(inputs["cover"]) if inputs.get("cover") else None
        if cover is not None and not cover.is_file():
            cover = None
        url = (inputs.get("audio_url") or "").strip()
        if url and not inputs.get("audio"):
            if not audio.is_file():  # «Перезапустить» с готовым in/input.mp3 не качает заново
                download_link(ctx, job.id, url, in_dir, job_dir / "download", thumbnail=cover is None)
            saved_thumb = in_dir / f"{INPUT_COVER_STEM}.jpg"
            if cover is None and saved_thumb.is_file():
                cover = saved_thumb
        if not audio.is_file():
            raise JobFailed("input", "Исходный mp3 не найден — загрузите файл и создайте задание заново")

        tracker = ProgressTracker()
        ctx.progress(job.id, tracker.set(*STAGE_PREPARE))
        work, out = job_dir / "us", job_dir / "out"
        for d in (work, out, job_dir / "result"):
            shutil.rmtree(d, ignore_errors=True)
        work.mkdir(parents=True)
        out.mkdir()
        us_in = work / f"{naming.base_name(job.artist, job.title)}.mp3"  # имя нужно MusicBrainz
        audio_only_copy(ctx, job.id, audio, us_in)
        lyrics = None
        if inputs.get("lyrics") and ctx.paths.abs(inputs["lyrics"]).is_file():
            text = prepare_lyrics(ultrastar.decode(ctx.paths.abs(inputs["lyrics"]).read_bytes())[0])
            if text:
                lyrics = work / "lyrics.txt"
                lyrics.write_text(text, "utf-8")

        timing = None
        lrc = ctx.paths.abs(inputs["lrc"]) if inputs.get("lrc") else None
        if lyrics is not None and p.get("lrc_timing") and lrc is not None and lrc.is_file():
            try:
                lrc_text = lrc.read_text("utf-8-sig")
            except (OSError, UnicodeError) as e:
                ctx.log(job.id, f"Тайминги LRC не использованы: {lrc.name} не прочитан "
                                f"({type(e).__name__}: {e})")
            else:
                if lrc_matches(text, lrc_text):
                    timing = lrc
                    ctx.log(job.id, "Тайминги строк — из LRC")
                else:
                    ctx.log(job.id, LRC_NOT_USED)

        cmd = ctx.ultrasinger_cmd() + ultrasinger_args(p, us_in, out, lyrics, dict(ctx.env),
                                                       lyrics_timing=timing)
        tail = ctx.run_command(job.id, cmd, tracker=tracker, cwd=ctx.ultrasinger_cwd())
        folders = [d for d in out.iterdir() if d.is_dir()]
        if len(folders) != 1:
            what = "нет выходной папки" if not folders else f"выходных папок {len(folders)}, ожидалась одна"
            last = "\n".join(tail[-5:])
            raise JobFailed("no_output", f"UltraSinger не создал результат ({what}) — проверьте модель "
                                         f"и параметры{chr(10) * 2 + 'Последние строки лога:' + chr(10) + last if last else ''}")
        ctx.check_cancel(job.id, force=True)

        ctx.progress(job.id, tracker.set(*STAGE_POSTPROCESS))
        if lyrics is not None and timing is None:  # с LRC строки уже заданы его метками
            align_lines(ctx, job.id, folders[0], text)
        try:
            fin = postprocess.finalize(folders[0], job.artist, job.title, cover, dest_dir=job_dir / "result",
                                       **chosen_video(ctx, job, in_dir))
        except postprocess.FinalizeError as e:
            raise JobFailed("postprocess", f"Ошибка постобработки: {e}") from None
        ctx.log(job.id, f"Постобработка: нот нулевой длины исправлено {fin.zero_fixed}"
                        + ("; данные MusicBrainz отброшены (другой исполнитель)" if fin.mb_dropped else ""))
        if p.get("keep_debug"):
            for f in out.rglob("lyrics_debug.json"):
                (job_dir / "debug").mkdir(exist_ok=True)
                shutil.copy2(f, job_dir / "debug" / f.name)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
        publish_song(ctx, job, job)


# ============================================================================ instrumental

def _instrumental_name(audio: str) -> str:
    """``<основа имени аудио> [Instrumental].mp3`` рядом с аудио (история 45)."""
    a = PurePosixPath(audio)
    return str(a.with_name(a.stem + naming.SUFFIX_INSTRUMENTAL))


def publish_instrumental(ctx: JobContext, job: Job, src: Job) -> None:
    p = src.params
    rel_dir, txt_name = p["rel_dir"], p["txt_name"]
    job_dir = ctx.paths.job(rel_dir, src.id)
    result = job_dir / "result"
    mp3s = [f for f in result.rglob("*.mp3")] if result.is_dir() else []
    if len(mp3s) != 1:
        raise JobFailed("publish", "ошибка выкладки: минусовка не найдена в томе")
    value = mp3s[0].relative_to(result).as_posix()
    _start_publish(ctx, job)
    txt_rel = f"{rel_dir}/{txt_name}"
    try:
        storage = ctx.storage(p.get("target_id"))
        txt = storage.read(txt_rel)
        try:
            new_txt = ultrastar.set_header_line(txt, "INSTRUMENTAL", value)
        except ValueError:
            raise JobFailed("publish", "ошибка выкладки: имя минусовки не записать в кодировке .txt") from None
        old = ultrastar.parse(txt).header("INSTRUMENTAL")
        for name in dict.fromkeys(n for n in (old, value) if n):
            if storage.exists(f"{rel_dir}/{name}"):
                ctx.trash.save_version(storage, f"{rel_dir}/{name}", reason="минусовка заменена")
                ctx.log(job.id, f"Прежняя минусовка «{name}» сохранена в корзине.")
        with open(mp3s[0], "rb") as f:
            storage.write_atomic(f"{rel_dir}/{value}", f)
        if new_txt != txt:
            ctx.trash.save_version(storage, txt_rel, reason="версия до минусовки")
            storage.write_atomic(txt_rel, new_txt)
        if old and old != value and storage.exists(f"{rel_dir}/{old}"):
            storage.delete_file(f"{rel_dir}/{old}")
    except (StorageError, TrashError, OSError) as e:
        raise _publish_error(ctx, e, target_id=p.get("target_id")) from None
    ctx.log(job.id, f"Минусовка выложена: {rel_dir}/{value}")
    _index(ctx, job, storage, rel_dir, None)
    remove_tree(job_dir)
    _done(ctx, job)


class InstrumentalHandler:
    needs_gpu = True

    def run(self, job: Job, ctx: JobContext) -> None:
        p = job.params
        rel_dir = p["rel_dir"]
        job_dir = ctx.paths.job(rel_dir, job.id)
        work, result = job_dir / "work", job_dir / "result"
        for d in (work, result):
            shutil.rmtree(d, ignore_errors=True)
        work.mkdir(parents=True)
        tracker = ProgressTracker(stages=[(("demucs",), "Отделение вокала", 5),
                                          (("ffmpeg",), "Минусовка в mp3", 85)], ceiling=95)
        ctx.progress(job.id, tracker.set(*STAGE_PREPARE))
        storage = _storage(ctx, p.get("target_id"))
        try:
            entry = storage.read_song(rel_dir)
            if entry is None:
                raise JobFailed("input", "Песня не найдена в папке результата")
            audio = entry.audio
            if not audio:
                raise JobFailed("input", "У песни нет аудиофайла (#AUDIO или #MP3)")
            src_audio = work / PurePosixPath(audio).name
            with storage.open_read(f"{rel_dir}/{audio}") as f, open(src_audio, "wb") as g:
                shutil.copyfileobj(f, g)
        except StorageError as e:
            _reset(ctx, p.get("target_id"))
            raise JobFailed("storage", f"Папка результата недоступна: {e}") from None
        ctx.log(job.id, f"Аудио песни: {audio}")

        ctx.progress(job.id, tracker.feed("demucs"))
        sep = work / "sep"
        ctx.run_command(job.id, ctx.demucs_cmd() + [
            "--two-stems", "vocals", "-n", "htdemucs", "-d", "cuda", "--float32",
            "--out", str(sep), str(src_audio)], tracker=tracker, what="Demucs")
        wav = sep / "htdemucs" / src_audio.stem / "no_vocals.wav"
        if not wav.is_file():
            raise JobFailed("no_output", "Demucs не создал минусовку (no_vocals.wav)")

        ctx.progress(job.id, tracker.feed("ffmpeg"))
        dest = result.joinpath(*PurePosixPath(_instrumental_name(audio)).parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        ctx.run_command(job.id, ctx.ffmpeg_cmd() + [
            "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(wav),
            "-codec:a", "libmp3lame", "-q:a", "0", str(dest)], what="ffmpeg")
        if not dest.is_file():
            raise JobFailed("no_output", "ffmpeg не создал mp3 минусовки")
        shutil.rmtree(work, ignore_errors=True)
        ctx.check_cancel(job.id, force=True)
        publish_instrumental(ctx, job, job)


# ============================================================================ import

YOUTUBE_FAILED = "YouTube не отдал звук"
CONVERT_MESSAGE = ("Не удалось перевести звук в mp3 — файл повреждён или формат не поддерживается; "
                   "загрузите другой файл")


def _log_tail(e: JobFailed) -> str:
    return e.user_message.partition("\n\n")[2]  # «Последние строки лога: …»


def _youtube_failed(reason: str, tail: str = "", what: str = YOUTUBE_FAILED) -> JobFailed:
    msg = f"{what}: {reason}"
    return JobFailed("youtube", f"{msg}\n\n{tail}" if tail else msg)


# Ролик убран с YouTube (удалён, закрыт, недоступен) — повод взять другую ссылку песни или поиск.
# 403, сеть и «нет формата» сюда не относятся: это сбой загрузки, а не мёртвая ссылка.
_GONE_MARKERS = ("video unavailable", "private video", "removed", "not available",
                 "this video has been removed", "http error 404", "http error 410")
YOUTUBE_GONE = "youtube_gone"


def _ytdlp_kind(cause: str, tail: str) -> str | None:
    """Вид сбоя yt-dlp: ``no_format``, ``forbidden`` (403), ``network``, ``gone`` (ролик убран) или None."""
    low = cause.lower()
    if "format is not available" in low:
        return "no_format"
    if "http error 403" in low:
        return "forbidden"
    if any(m in tail for m in _NETWORK_MARKERS):
        return "network"
    return "gone" if any(m in low for m in _GONE_MARKERS) else None


def _ytdlp_reason(tail: str) -> str:
    """Причина из вывода yt-dlp: последняя строка ``ERROR: …``."""
    errors = [ln.strip() for ln in tail.splitlines() if ln.strip().startswith("ERROR:")]
    if errors:
        return errors[-1][len("ERROR:"):].strip()
    return "yt-dlp завершился с ошибкой"


def ytdlp_failure(e: JobFailed, what: str, *, reason: str = "youtube", texts: dict[str, str] | None = None,
                  gone_reason: str | None = YOUTUBE_GONE) -> JobFailed:
    """Сбой yt-dlp → ``JobFailed`` — единый разбор вывода для звука и видео: причина — последняя
    строка ``ERROR:``, вид — ``_ytdlp_kind``. Текст — ``texts[вид]`` или «``what``: причина»
    (``what`` — подпись: «YouTube не отдал звук», «Не удалось скачать видео»…), к нему — хвост лога.
    Убранный ролик получает ``gone_reason`` (повод взять другую ссылку песни)."""
    tail = _log_tail(e)
    cause = _ytdlp_reason(tail)
    kind = _ytdlp_kind(cause, tail)
    msg = (texts or {}).get(kind) or f"{what}: {cause}"
    failed = JobFailed(reason, f"{msg}\n\n{tail}" if tail else msg)
    if kind == "gone" and gone_reason:
        failed.reason = gone_reason
    return failed


def download_youtube(ctx: JobContext, job_id: int, url: str, work: Path,
                     thumbnail: bool, what: str = YOUTUBE_FAILED) -> tuple[Path, Path | None]:
    """Звук (и миниатюра) через yt-dlp (YouTube и всё, что он умеет). Возвращает (mp3, jpg или None).
    ``-4``: у контейнеров нет IPv6-маршрута, а сайты отдают AAAA первыми."""
    work.mkdir(parents=True, exist_ok=True)
    template = work / "youtube.%(ext)s"
    cmd = ctx.ytdlp_cmd() + ["-4", "-x", "--audio-format", "mp3", "--no-playlist", "--newline",
                             "-o", str(template)]
    if thumbnail:
        cmd += ["--write-thumbnail", "--convert-thumbnails", "jpg"]
    try:
        ctx.run_command(job_id, cmd + ["--", url], tracker=DownloadTracker(), what="yt-dlp")
    except JobFailed as e:
        raise ytdlp_failure(e, what) from None
    mp3 = work / "youtube.mp3"
    if not mp3.is_file():
        raise _youtube_failed("yt-dlp не создал mp3", what=what)
    jpg = work / "youtube.jpg"
    return mp3, (jpg if thumbnail and jpg.is_file() else None)


SEARCH_COUNT = 5
SEARCH_SLACK_MS = 2000  # ролик может быть короче конца нот не больше чем на 2 с
SEARCH_NOTHING = ("Ролик из песни удалён с YouTube, а поиск не нашёл подходящего — вставьте свою ссылку "
                  "или загрузите mp3 и перезапустите импорт")


def song_end_ms(song: ultrastar.Song) -> float | None:
    """Конец последней ноты в мс по #BPM/#GAP; None — нот нет, #RELATIVE или нет #BPM."""
    notes = song.notes()
    if not notes or song.relative:
        return None
    try:
        return ultrastar.beat_to_ms(song, max(n.end for n in notes))
    except ValueError:
        return None


def rank_search_results(entries: list[dict], end_ms: float | None) -> list[dict]:
    """Кандидаты поиска YouTube от лучшего: длительность ближе к концу нот, при равенстве — раньше
    в выдаче; короче ``end_ms − 2 с`` и без длительности — отброшены. Без ``end_ms`` — порядок выдачи."""
    fit = []
    for i, e in enumerate(entries):
        dur = e.get("duration") if isinstance(e, dict) else None
        if not isinstance(dur, (int, float)) or isinstance(dur, bool) or dur <= 0:
            continue
        if not (e.get("url") or e.get("id")):
            continue
        dur_ms = dur * 1000.0
        if end_ms is not None and dur_ms < end_ms - SEARCH_SLACK_MS:
            continue
        fit.append((abs(dur_ms - end_ms) if end_ms is not None else 0.0, i, e))
    fit.sort(key=lambda t: (t[0], t[1]))
    return [e for _, _, e in fit]


def entry_url(entry: dict) -> str:
    url = entry.get("url") or ""
    if url.startswith("http"):
        return url
    return f"https://www.youtube.com/watch?v={entry.get('id') or url}"


def mmss(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def search_youtube(ctx: JobContext, job_id: int, query: str, count: int = SEARCH_COUNT) -> list[dict]:
    """``ytsearchN:<запрос>`` через ``yt-dlp -4 -J --flat-playlist`` (только метаданные)."""
    out: list[str] = []
    try:
        ctx.run_command(job_id, ctx.ytdlp_cmd() + ["-4", "-J", "--flat-playlist", "--",
                                                   f"ytsearch{count}:{query}"], what="yt-dlp", json_out=out)
    except JobFailed as e:
        raise ytdlp_failure(e, YOUTUBE_FAILED, gone_reason=None) from None
    for line in reversed(out):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        entries = data.get("entries") if isinstance(data, dict) else None
        return [x for x in entries if isinstance(x, dict)] if isinstance(entries, list) else []
    return []


def download_song_youtube(ctx: JobContext, job: Job, url: str, work: Path, thumbnail: bool,
                          end_ms: float | None) -> tuple[Path, Path | None]:
    """Звук импорта с YouTube. Ролик песни убран → прочие её ссылки по порядку, затем (ссылка не своя)
    поиск «исполнитель - название» с длительностью под ноты. 403, сеть и своя ссылка — ошибка как есть."""
    p = job.params

    def attempt(link: str) -> tuple[Path, Path | None]:
        shutil.rmtree(work, ignore_errors=True)
        return download_youtube(ctx, job.id, link, work, thumbnail=thumbnail)

    try:
        return attempt(url)
    except JobFailed as e:
        if e.reason != YOUTUBE_GONE or p.get("youtube_from_user"):
            raise
    for alt in p.get("youtube_alternatives") or []:
        alt = (alt or "").strip()
        if not alt or alt == url:
            continue
        ctx.log(job.id, f"Ссылка из песни недоступна — беру {alt}")
        try:
            return attempt(alt)
        except JobFailed as e:
            if e.reason != YOUTUBE_GONE:
                raise
    query = f"{job.artist} - {job.title}"
    ctx.log(job.id, f"Ссылка из песни недоступна — беру поиск YouTube: {query}")
    for entry in rank_search_results(search_youtube(ctx, job.id, query), end_ms):
        ctx.check_cancel(job.id, force=True)
        ctx.log(job.id, f"Найден ролик «{entry.get('title') or entry.get('id')}» ({mmss(entry['duration'])}) — "
                        "ноты сделаны под другую запись, слова могут разъехаться")
        try:
            return attempt(entry_url(entry))
        except JobFailed as e:
            if e.reason != YOUTUBE_GONE:
                raise
    raise JobFailed(YOUTUBE_GONE, SEARCH_NOTHING)


LINK_FAILED = "Не удалось скачать звук по ссылке"
YANDEX_FAILED = "Яндекс Музыка не отдала звук"


def _download_yandex(ctx: JobContext, job_id: int, url: str, dest: Path) -> None:
    """Трек Яндекс Музыки через ``MUSICLINK_CMD download <url> <dest>``; ключ доступа из «Настроек» —
    только в окружении подпроцесса (не в argv и не в лог)."""
    ym_key = ctx.settings.get_yandex()
    if not ym_key:
        raise JobFailed("yandex_no_token", musiclink.MSG_NEED_LOGIN)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        ctx.run_command(job_id, ctx.musiclink_cmd() + ["download", url, str(dest)], what="musiclink",
                        extra_env={"YANDEX_MUSIC_TOKEN": ym_key})
    except JobFailed as e:
        tail = _log_tail(e)
        lines = [ln.strip() for ln in tail.splitlines()[1:] if ln.strip()]  # без «Последние строки лога:»
        reason = lines[-1] if lines else YANDEX_FAILED
        raise JobFailed("download", f"{reason}\n\n{tail}" if tail else reason) from None
    if not dest.is_file():
        raise JobFailed("download", f"{YANDEX_FAILED}: файл не создан")


def download_link(ctx: JobContext, job_id: int, url: str, in_dir: Path, work: Path,
                  thumbnail: bool) -> None:
    """Звук по ссылке (``inputs.audio_url``) → ``in/input.mp3``; миниатюра yt-dlp → ``in/cover.jpg``
    (если ``thumbnail``). Сразу в in/: сбой дальше не заставит «Перезапустить» качать заново."""
    try:
        link = musiclink.classify(url)
    except musiclink.MusicLinkError as e:
        raise JobFailed("input", str(e)) from None
    ctx.progress(job_id, STAGE_DOWNLOAD)
    ctx.log(job_id, f"Звук по ссылке: {link.url}")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    in_dir.mkdir(parents=True, exist_ok=True)
    if musiclink.is_yandex(link):
        mp3 = work / INPUT_AUDIO
        _download_yandex(ctx, job_id, link.url, mp3)
    else:
        mp3, thumb = download_youtube(ctx, job_id, link.url, work, thumbnail=thumbnail, what=LINK_FAILED)
        if thumb is not None:
            shutil.copy2(thumb, in_dir / f"{INPUT_COVER_STEM}.jpg")
    ctx.check_cancel(job_id, force=True)
    shutil.copy2(mp3, in_dir / INPUT_AUDIO)
    shutil.rmtree(work, ignore_errors=True)


def to_mp3(ctx: JobContext, job_id: int, src: Path, dest: Path) -> None:
    """Звук в mp3 с одним аудиопотоком: mp3 — копия потока, прочее — перекодирование."""
    if src.suffix.lower() == ".mp3":
        audio_only_copy(ctx, job_id, src, dest)
        return
    try:
        ctx.run_command(job_id, ctx.ffmpeg_cmd() + [
            "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(src),
            "-map", "0:a:0", "-codec:a", "libmp3lame", "-q:a", "0", str(dest)], what="ffmpeg")
    except JobFailed as e:
        tail = _log_tail(e)
        raise JobFailed("input", f"{CONVERT_MESSAGE}\n\n{tail}" if tail else CONVERT_MESSAGE) from None
    if not dest.is_file():
        raise JobFailed("input", CONVERT_MESSAGE)


def _enqueue_instrumental(ctx: JobContext, job: Job, src: Job, storage: Storage, rel_dir: str) -> Job | None:
    """Импорт с галочкой «Сделать минусовку» → обычное задание instrumental (история 19).
    Сбой постановки импорт не роняет — песня уже выложена."""
    try:
        entry = storage.read_song(rel_dir)
        if entry is None or not entry.audio:
            raise ValueError("песня или её аудио не найдены в папке результата")
        params = instrumental_params(rel_dir=rel_dir, txt_name=entry.txt_name, audio=entry.audio,
                                     instrumental=entry.instrumental, target_id=storage.target_id)
        inst = ctx.jobs.enqueue("instrumental", {"artist": entry.artist or src.artist,
                                                 "title": entry.title or src.title,
                                                 "song_id": song_id_for(storage.target_id, rel_dir)},
                                params, parent_id=src.id)
        ctx.log(job.id, f"Поставлено задание минусовки #{inst.id}.")
        return inst
    except Exception as e:  # noqa: BLE001
        ctx.log(job.id, f"Предупреждение: минусовка не поставлена: {e}")
        return None


class ImportHandler:
    """Готовая песня UltraStar (usdb, сборник, файлы) → папка песни → выкладка (Решения §6)."""
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        p = job.params
        rel_dir = _song_rel_dir(job)
        job_dir = ctx.paths.job(rel_dir, job.id)
        inputs = p.get("inputs") or {}
        in_dir = ctx.paths.abs(inputs["dir"]) if inputs.get("dir") else ctx.paths.job_in(rel_dir, job.id)
        txt = ctx.paths.abs(inputs["txt"]) if inputs.get("txt") else None
        if txt is None or not txt.is_file():
            raise JobFailed("input", "Файл песни (.txt) не найден — импортируйте песню заново")
        work, folder_root = job_dir / "work", job_dir / "import"
        for d in (work, folder_root, job_dir / "result"):
            shutil.rmtree(d, ignore_errors=True)
        work.mkdir(parents=True)
        base = naming.base_name(job.artist, job.title)
        folder = folder_root / base
        folder.mkdir(parents=True)
        mp3 = folder / f"{base}.mp3"
        saved_mp3 = in_dir / INPUT_AUDIO

        saved_thumb = in_dir / f"{INPUT_COVER_STEM}.jpg"
        cover = ctx.paths.abs(inputs["cover"]) if inputs.get("cover") else None
        if cover is not None and not cover.is_file():
            cover = None
        audio = ctx.paths.abs(inputs["audio"]) if inputs.get("audio") else None
        if audio is None and saved_mp3.is_file():
            # «Перезапустить»: звук (и миниатюра) уже скачаны прошлым запуском
            audio = saved_mp3
            if cover is None and saved_thumb.is_file():
                cover = saved_thumb
        if audio is None:
            url = (p.get("youtube_url") or "").strip()
            if not url:
                raise JobFailed("input", "Нужен звук: загрузите mp3 или вставьте ссылку на YouTube")
            ctx.progress(job.id, STAGE_DOWNLOAD)
            ctx.log(job.id, f"Звук с YouTube: {url}")
            try:
                end_ms = song_end_ms(ultrastar.parse(txt.read_bytes()))
            except ValueError:  # битый .txt упадёт ниже с понятной ошибкой
                end_ms = None
            audio, thumb = download_song_youtube(ctx, job, url, work, thumbnail=cover is None, end_ms=end_ms)
            if thumb is not None:
                shutil.copy2(thumb, saved_thumb)
                cover = saved_thumb
            # сразу в in/: сбой на «Подготовке» не заставит «Перезапустить» качать заново
            shutil.copy2(audio, saved_mp3)
            audio = saved_mp3
            ctx.check_cancel(job.id, force=True)
        elif not audio.is_file():
            raise JobFailed("input", "Звук песни не найден — импортируйте песню заново")

        ctx.progress(job.id, IMPORT_PREPARE)
        to_mp3(ctx, job.id, audio, mp3)
        if not saved_mp3.is_file():
            shutil.copy2(mp3, saved_mp3)  # source/ должен позволять перегенерацию (история 23)

        song = ultrastar.parse(txt.read_bytes())
        for key in ("VIDEO", "BACKGROUND", "VIDEOGAP"):
            song.remove_header(key)
        song.set_header("MP3", mp3.name)
        song.set_header("AUDIO", mp3.name)
        (folder / f"{base}.txt").write_bytes(ultrastar.render(song))
        try:
            fin = postprocess.finalize(folder, job.artist, job.title, cover, dest_dir=job_dir / "result",
                                       **chosen_video(ctx, job, in_dir))
        except postprocess.FinalizeError as e:
            raise JobFailed("postprocess", f"Ошибка подготовки песни: {e}") from None
        except UnicodeEncodeError:
            raise JobFailed("postprocess", "Ошибка подготовки песни: имя файла не записать в .txt") from None
        ctx.log(job.id, f"Подготовка: нот нулевой длины исправлено {fin.zero_fixed}; "
                        f"обложка: {'есть' if cover is not None else 'нет'}")
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(folder_root, ignore_errors=True)
        ctx.check_cancel(job.id, force=True)
        publish_song(ctx, job, job)


# ============================================================================ video

VIDEO_FAILED = "Не удалось скачать видео"
VIDEO_NO_FORMAT = ("По ссылке нет видео (сайт не отдал видеодорожку) — возможно, это ссылка на музыку; "
                   "вставьте ссылку на ролик или загрузите файл")
VIDEO_FORBIDDEN = "Сайт видео отказал в доступе (HTTP 403) — попробуйте позже или обновите yt-dlp"
VIDEO_NETWORK = "Нет связи с сайтом видео — проверьте интернет и попробуйте ещё раз"
VIDEO_TEXTS = {"no_format": VIDEO_NO_FORMAT, "forbidden": VIDEO_FORBIDDEN, "network": VIDEO_NETWORK}
VIDEO_YANDEX = "Яндекс Музыка отдаёт только звук — вставьте ссылку на видео"


def _video_sort(height) -> str:
    """``-S`` yt-dlp: ``res:H`` — ровно H, иначе ближайшее снизу, иначе сверху; 0 — лучшее."""
    try:
        h = int(height or 0)
    except (TypeError, ValueError):
        h = 0
    return f"res:{h},vcodec:h264,ext:mp4" if h > 0 else "vcodec:h264,ext:mp4"


def download_video(ctx: JobContext, job_id: int, url: str, dest_dir: Path, height) -> Path:
    """Только видеодорожка по ссылке (yt-dlp; H.264/mp4 в приоритете, ``height`` 0 — лучшее) →
    ``dest_dir/video.mp4``. Качается во временную ``dest_dir/.video-download``: недокачанное
    «Перезапустить» не примет за готовое."""
    try:
        link = musiclink.classify(url)
    except musiclink.MusicLinkError as e:
        raise JobFailed("input", str(e)) from None
    if musiclink.is_yandex(link):
        raise JobFailed("input", VIDEO_YANDEX)
    ctx.progress(job_id, STAGE_VIDEO_DOWNLOAD)
    ctx.log(job_id, f"Видео по ссылке: {link.url}")
    work = dest_dir / ".video-download"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    cmd = ctx.ytdlp_cmd() + ["-4", "--no-playlist", "--newline", "-f", "bv*", "-S", _video_sort(height),
                             "--remux-video", "mp4", "-o", str(work / "video.%(ext)s"), "--", link.url]
    tracker = DownloadTracker(start=STAGE_VIDEO_DOWNLOAD[1], end=90, stage=STAGE_VIDEO_DOWNLOAD[0])
    try:
        ctx.run_command(job_id, cmd, tracker=tracker, what="yt-dlp")
    except JobFailed as e:
        raise ytdlp_failure(e, VIDEO_FAILED, reason="video", texts=VIDEO_TEXTS, gone_reason=None) from None
    found = sorted(f for f in work.iterdir() if f.is_file() and f.suffix.lower() in naming.VIDEO_EXTS)
    if not found:
        raise JobFailed("video", f"{VIDEO_FAILED}: yt-dlp не создал видеофайл")
    ctx.check_cancel(job_id, force=True)
    dest = dest_dir / f"{INPUT_VIDEO_STEM}{found[0].suffix.lower()}"
    os.replace(found[0], dest)
    shutil.rmtree(work, ignore_errors=True)
    return dest


VIDEO_SKIPPED = "Видео не скачалось: {reason}, песня выложена без видео"


def chosen_video(ctx: JobContext, job: Job, in_dir: Path) -> dict:
    """Видео блока «Видео» generate/import (``params.video``) → kwargs ``finalize``.

    Файл — ``inputs.video`` (форма, архив) или уже скачанный ``in/video.*`` («Перезапустить»
    не качает заново); иначе ссылка качается после звука. Сбой скачивания — строка лога,
    песня выкладывается без видео (история 27). Без видео — ``{}``.
    """
    video = job.params.get("video") or {}
    if not video or video.get("mode") in (None, "none"):
        return {}
    inputs = job.params.get("inputs") or {}
    src = ctx.paths.abs(inputs["video"]) if inputs.get("video") else None
    if src is None or not src.is_file():
        src = _saved_video(in_dir)
    if src is None and (video.get("url") or "").strip():
        in_dir.mkdir(parents=True, exist_ok=True)
        try:
            src = download_video(ctx, job.id, video["url"].strip(), in_dir, video.get("height"))
        except JobFailed as e:
            ctx.log(job.id, VIDEO_SKIPPED.format(reason=(e.user_message or str(e)).split("\n")[0].rstrip(".")))
            return {}
    if src is None or src.suffix.lower() not in naming.VIDEO_EXTS:
        ctx.log(job.id, VIDEO_SKIPPED.format(reason="видеофайл не найден"))
        return {}
    ctx.log(job.id, f"Видео: {src.name}")
    return {"video_path": src, "videogap": video.get("gap")}


def _saved_video(in_dir: Path) -> Path | None:
    if not in_dir.is_dir():
        return None
    found = sorted(f for f in in_dir.iterdir() if f.is_file() and _is_input_video(f))
    return found[0] if found else None


def publish_video(ctx: JobContext, job: Job, src: Job) -> None:
    """Видео из ``jobs/<id>/result/`` → папка песни; в ``.txt`` меняются только ``#VIDEO``/``#VIDEOGAP``
    (прежняя версия ``.txt`` — в корзину); старый видеофайл с другим именем удаляется (в корзину — нет)."""
    p = src.params
    rel_dir, txt_name = p["rel_dir"], p["txt_name"]
    job_dir = ctx.paths.job(rel_dir, src.id)
    result = job_dir / "result"
    remove = bool(p.get("remove"))
    video = None
    if not remove:
        found = [f for f in result.iterdir() if f.is_file()] if result.is_dir() else []
        if len(found) != 1:
            raise JobFailed("publish", "ошибка выкладки: видео не найдено в томе")
        video = found[0]
    _start_publish(ctx, job)
    txt_rel = f"{rel_dir}/{txt_name}"
    try:
        storage = ctx.storage(p.get("target_id"))
        txt = storage.read(txt_rel)
        song = ultrastar.parse(txt)
        old = naming.video_file_name(song.header("VIDEO"))
        if remove:
            changed = [song.remove_header(k) for k in ("VIDEO", "VIDEOGAP")]
            new_txt = ultrastar.render(song) if any(changed) else txt
        else:
            try:
                new_txt = ultrastar.set_header_line(txt, "VIDEO", video.name)
                if p.get("videogap") is not None:
                    new_txt = _set_videogap(new_txt, postprocess.format_videogap(p["videogap"]))
            except ValueError:
                raise JobFailed("publish", "ошибка выкладки: имя видео не записать в кодировке .txt") from None
            with open(video, "rb") as f:
                storage.write_atomic(f"{rel_dir}/{video.name}", f)
        if new_txt != txt:
            ctx.trash.save_version(storage, txt_rel,
                                   reason="версия до удаления видео" if remove else "версия до видео")
            storage.write_atomic(txt_rel, new_txt)
        if old and (remove or old.casefold() != video.name.casefold()) and storage.exists(f"{rel_dir}/{old}"):
            storage.delete_file(f"{rel_dir}/{old}")
            ctx.log(job.id, f"Прежнее видео «{old}» удалено.")
    except (StorageError, TrashError, OSError) as e:
        raise _publish_error(ctx, e, target_id=p.get("target_id")) from None
    ctx.log(job.id, f"Видео убрано: {rel_dir}" if remove else f"Видео выложено: {rel_dir}/{video.name}")
    _index(ctx, job, storage, rel_dir, None)
    remove_tree(job_dir)
    _done(ctx, job)


class VideoHandler:
    """Видео к песне в папке результата (истории 14–20): файл ``inputs.video``, ссылка
    ``video_url`` (качество ``video_height``) или ``remove``; без GPU."""
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        p = job.params
        rel_dir, txt_name = p["rel_dir"], p["txt_name"]
        job_dir = ctx.paths.job(rel_dir, job.id)
        result = job_dir / "result"
        shutil.rmtree(result, ignore_errors=True)
        result.mkdir(parents=True)
        if not p.get("remove"):
            inputs = p.get("inputs") or {}
            in_dir = ctx.paths.abs(inputs["dir"]) if inputs.get("dir") else ctx.paths.job_in(rel_dir, job.id)
            src = ctx.paths.abs(inputs["video"]) if inputs.get("video") else None
            if src is None or not src.is_file():
                src = _saved_video(in_dir)  # «Перезапустить» не качает заново
            if src is None:
                url = (p.get("video_url") or "").strip()
                if not url:
                    raise JobFailed("input", "Нужно видео: загрузите файл или вставьте ссылку")
                in_dir.mkdir(parents=True, exist_ok=True)
                src = download_video(ctx, job.id, url, in_dir, p.get("video_height"))
            ext = src.suffix.lower()
            if ext not in naming.VIDEO_EXTS:
                raise JobFailed("input", f"Формат видео {ext or 'без расширения'} не поддерживается")
            dest = result / (PurePosixPath(txt_name).stem + naming.video_suffix(ext))
            try:
                os.link(src, dest)  # тот же том: без второй копии сотен МБ
            except OSError:
                shutil.copy2(src, dest)
            ctx.log(job.id, f"Видео песни: {dest.name}")
        ctx.check_cancel(job.id, force=True)
        publish_video(ctx, job, job)


# ============================================================================ publish

class PublishHandler:
    """«Выложить повторно»: результат упавшего на выкладке задания (без GPU)."""
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        src = ctx.jobs.get(job.params.get("source_job_id") or job.parent_id or 0)
        if src is None:
            raise JobFailed("input", "Исходное задание для выкладки не найдено")
        if src.type in ("generate", "import"):
            publish_song(ctx, job, src)
        elif src.type == "instrumental":
            publish_instrumental(ctx, job, src)
        elif src.type == "video":
            publish_video(ctx, job, src)
        elif src.type == "audio":  # library-tools 08
            from .audiofix import publish_audio
            publish_audio(ctx, job, src)
        elif src.type == "artwork":  # library-tools 07
            from .artwork import publish_artwork
            publish_artwork(ctx, job, src)
        else:
            raise JobFailed("input", f"Задание типа «{src.type}» нельзя выложить повторно")


# ============================================================================ copy

COPY_RETRY_S = 60  # ожидающее копирование повторяется раз в минуту (история 36)
COPY_LOG_EVERY_S = 600  # строка «недоступно» в логе — не чаще раза в 10 минут


class CopyHandler:
    """«Копирование»: папка песни из одного хранилища в другое (Решения §9, истории 18–22, 36)."""
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        p = job.params
        rel_dir = p.get("rel_dir") or ""
        if not rel_dir or not p.get("from_target") or not p.get("to_target"):
            raise JobFailed("input", "Задание копирования без песни или хранилищ")
        src_name, dst_name = _target_name(ctx, p["from_target"]), _target_name(ctx, p["to_target"])
        ctx.check_cancel(job.id, force=True)
        after = p.get("after_job")
        dep = ctx.jobs.get(after) if after else None
        if dep is not None and dep.state not in FINAL_STATES:
            # минусовка ещё делается — копировать песню без неё нельзя
            self._wait(ctx, job, f"Ждёт задание #{after}", f"Ждёт окончания задания #{after}.")
            return
        in_dir = self._download(ctx, job, rel_dir, src_name)
        try:
            ctx.target_of(p["to_target"])
        except StorageError as e:
            raise JobFailed("storage", f"Хранилище «{dst_name}»: {e}") from None
        ctx.check_cancel(job.id, force=True)
        ctx.jobs.update(job.id, state="running", stage=STAGE_COPY[0], percent=STAGE_COPY[1])
        item = None
        try:
            target = ctx.storage(p["to_target"])
            if target.exists(rel_dir):
                if not p.get("replace"):
                    ctx.log(job.id, f"Уже есть в «{dst_name}» — пропущено.")
                    remove_tree(ctx.paths.job(rel_dir, job.id))
                    _done(ctx, job)
                    return
                item = ctx.trash.move_to_trash(target, rel_dir, reason="заменена копией")
                ctx.log(job.id, f"Прежняя версия в «{dst_name}» перенесена в корзину ({item.id}).")
            written = target.upload_dir(in_dir, rel_dir)
        except (StorageError, TrashError, OSError) as e:
            note = ""
            if item is not None:
                try:
                    if target.exists(rel_dir):
                        target.delete_dir(rel_dir)
                    ctx.trash.restore(target, item.id)
                    note = "; прежняя версия возвращена на место"
                except (StorageError, TrashError, OSError) as e2:
                    note = f"; прежняя версия осталась в корзине ({e2})"
            _reset(ctx, p["to_target"])
            if p.get("wait"):
                self._wait(ctx, job, f"Ждёт хранилище «{dst_name}»",
                           f"Хранилище «{dst_name}» недоступно: {e}{note}; повтор через минуту.")
                return
            raise JobFailed("storage", f"Хранилище «{dst_name}» недоступно: {e}{note}") from None
        ctx.log(job.id, f"Выложено в «{target.label}»: {rel_dir} ({len(written)} файлов).")
        removed = self._trash_replaced(ctx, job, target, rel_dir, dst_name)
        own = ctx.library.get(ctx.target_of(p["from_target"]).id, rel_dir)
        _index(ctx, job, target, rel_dir, own.own_song_id if own else None, removed=removed)
        remove_tree(ctx.paths.job(rel_dir, job.id))
        _done(ctx, job)

    @staticmethod
    def _download(ctx: JobContext, job: Job, rel_dir: str, src_name: str) -> Path:
        return download_song_dir(ctx, job, rel_dir, job.params["from_target"], src_name)

    @staticmethod
    def _trash_replaced(ctx: JobContext, job: Job, target: Storage, rel_dir: str, name: str) -> str | None:
        """Замена с другой папкой (§8): прежняя версия ``replace_rel_dir`` — в корзину цели."""
        old = job.params.get("replace_rel_dir")
        if not old or old == rel_dir:
            return None
        try:
            if not target.exists(old):
                return None
            item = ctx.trash.move_to_trash(target, old, reason="заменена новой версией")
            ctx.log(job.id, f"Прежняя версия «{old}» в «{name}» перенесена в корзину ({item.id}).")
            return old
        except (StorageError, TrashError, OSError) as e:
            ctx.log(job.id, f"Предупреждение: прежняя версия «{old}» в «{name}» не перенесена в корзину: {e}")
            return None

    @staticmethod
    def _wait(ctx: JobContext, job: Job, stage: str, message: str) -> None:
        wait_retry(ctx, job, stage, message)


def download_song_dir(ctx: JobContext, job: Job, rel_dir: str, target_id: str, name: str) -> Path:
    """Папка песни ``rel_dir`` из хранилища ``target_id`` в ``jobs/<id>/in/`` (общее у ``copy``
    и ``rename``); уже скачанная (ожидание) или вход родителя (restart) — повторно не качается.
    Хранилище недоступно — ``JobFailed("storage")``, песни нет — ``JobFailed("source")``."""
    in_dir = ctx.paths.job_in(rel_dir, job.id)
    if in_dir.is_dir():
        return in_dir
    prev = ctx.paths.job_in(rel_dir, job.parent_id) if job.parent_id else None
    if prev is not None and prev.is_dir():  # «Перезапустить»: вход родителя уже скачан
        in_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(prev), str(in_dir))
        remove_tree(prev.parent)
        ctx.log(job.id, "Папка песни уже скачана прежним заданием — повторно не качается.")
        return in_dir
    ctx.jobs.update(job.id, stage=STAGE_COPY_DOWNLOAD[0], percent=STAGE_COPY_DOWNLOAD[1])
    ctx.log(job.id, f"Скачивание из «{name}»: {rel_dir}")
    tmp = in_dir.with_name("in.part")
    try:
        source = ctx.storage(target_id)
        if source.read_song(rel_dir) is None:
            raise JobFailed("source", f"Песни «{rel_dir}» нет в «{name}»")
        shutil.rmtree(tmp, ignore_errors=True)
        source.download_dir(rel_dir, tmp)
        tmp.rename(in_dir)
    except (StorageError, OSError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        _reset(ctx, target_id)
        raise JobFailed("storage", f"Хранилище-источник «{name}» недоступно: {e}") from None
    except JobFailed:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return in_dir


def wait_retry(ctx: JobContext, job: Job, stage: str, message: str) -> None:
    """Задание ждёт (хранилище недоступно или минусовка не готова): обратно в очередь, повтор
    через ``COPY_RETRY_S``; строка лога — не чаще раза в ``COPY_LOG_EVERY_S``."""
    ctx.check_cancel(job.id, force=True)
    p = dict(job.params)
    last = p.get("wait_logged_at")
    if not last or datetime.fromisoformat(now()) - datetime.fromisoformat(last) >= timedelta(
            seconds=COPY_LOG_EVERY_S):
        ctx.log(job.id, message)
        p["wait_logged_at"] = now()
    p["retry_at"] = now(COPY_RETRY_S)
    ctx.jobs.update(job.id, state="queued", stage=stage, params=p)


# ============================================================================ rename

# Заголовки .txt — ссылки на файлы папки песни: при переименовании файла меняются вместе с ним.
RENAME_FILE_HEADERS = ("MP3", "AUDIO", "COVER", "VIDEO", "INSTRUMENTAL", "VOCALS", "BACKGROUND")
RENAME_REASON = "переименована"


def rename_txt(data: bytes, artist: str, title: str, renamed: dict[str, str]) -> bytes:
    """``#ARTIST``/``#TITLE`` и заголовки-ссылки на переименованные файлы (``RENAME_FILE_HEADERS``,
    сравнение без регистра); прочие байты не меняются. Не записать в кодировке — ``ValueError``."""
    folded = {old.casefold(): new for old, new in renamed.items() if old != new}
    song = ultrastar.parse(data)
    for key in RENAME_FILE_HEADERS:
        value = (song.header(key) or "").strip()
        new = folded.get(value.casefold()) if value else None
        if new is not None:
            data = ultrastar.set_header_line(data, key, new)
    for key, value in (("ARTIST", artist), ("TITLE", title)):
        if (song.header(key) or "") != value:
            data = ultrastar.set_header_line(data, key, value)
    return data


class _Retry(Exception):
    """Хранилище перестало отвечать посреди переименования (``note`` — что осталось не на месте)."""

    def __init__(self, error: Exception, note: str = ""):
        super().__init__(str(error))
        self.error, self.note = error, note


def _alive(storage: Storage) -> bool:
    """Отвечает ли хранилище (корень читается)."""
    try:
        storage.listdir("")
        return True
    except StorageError:
        return False


def _same_file(storage: Storage, rel: str, data: bytes | None) -> bool:
    """Файл ``rel`` есть в хранилище и байт в байт равен ``data``."""
    if data is None:
        return False
    try:
        return storage.read(rel) == data
    except StorageNotFound:
        return False


def _old_alive(storage: Storage, rel_dir: str, txt_name: str) -> bool:
    """Прежняя папка песни ещё в хранилище (есть её ``.txt``)."""
    return storage.exists(f"{rel_dir}/{txt_name}" if txt_name else rel_dir)


class RenameHandler:
    """«Переименование» одной копии песни в её хранилище: папка и файлы под новым
    «Исполнитель - Название», в ``.txt`` — имя и ссылки на файлы; старая папка — в корзину (без GPU)."""
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        p = job.params
        rel_dir, new_rel = p.get("rel_dir") or "", p.get("new_rel_dir") or ""
        target_id, artist, title = p.get("target_id"), p.get("artist") or "", p.get("title") or ""
        if not rel_dir or not new_rel or not target_id or not artist or not title:
            raise JobFailed("input", "Задание переименования без песни, хранилища или нового имени")
        name = _target_name(ctx, target_id)
        ctx.check_cancel(job.id, force=True)
        try:
            ctx.target_of(target_id)
        except StorageError as e:
            raise JobFailed("storage", f"Хранилище «{name}»: {e}") from None
        try:
            in_dir = download_song_dir(ctx, job, rel_dir, target_id, name)
        except JobFailed as e:
            if e.reason == "storage" and p.get("wait"):
                wait_retry(ctx, job, f"Ждёт хранилище «{name}»", f"{e.user_message}; повтор через минуту.")
                return
            raise
        result, new_txt_name = self._build(ctx, job, in_dir)
        new_txt = (result / new_txt_name).read_bytes()
        ctx.check_cancel(job.id, force=True)
        ctx.jobs.update(job.id, state="running", stage=STAGE_RENAME[0], percent=STAGE_RENAME[1])
        same_dir = new_rel.casefold() == rel_dir.casefold()  # на SMB/Windows — та же папка
        try:
            storage = ctx.storage(target_id)
            # своя недописанная выкладка (воркер упал после неё): .txt байт в байт как наш
            done_before = _same_file(storage, f"{new_rel}/{new_txt_name}", new_txt)
            old_here = _old_alive(storage, rel_dir, p.get("txt_name") or "")
            if not same_dir and not done_before and storage.exists(new_rel):
                if p.get("upload_started") != new_rel or storage.read_song(new_rel) is not None:
                    raise JobFailed("conflict", f"Песня «{artist} — {title}» уже есть в «{name}»")
                # недописанная выкладка этого задания или его родителя — заново
                storage.delete_dir(new_rel)
                ctx.log(job.id, f"Недописанная папка «{new_rel}» прежней попытки удалена.")
        except StorageError as e:
            return self._unavailable(ctx, job, name, e)
        if done_before:
            ctx.log(job.id, f"Папка «{new_rel}» уже выложена прежним заданием — доводятся остальные шаги.")
        else:
            if p.get("upload_started") != new_rel:  # переживает ожидание и «Перезапустить»
                p = job.params = {**p, "upload_started": new_rel}
                ctx.jobs.update(job.id, params=p)
            try:
                self._publish(ctx, job, storage, result, same_dir and old_here)
            except _Retry as r:
                return self._unavailable(ctx, job, name, r.error, r.note)
        removed = rel_dir  # в индексе старой строки быть не должно (папки уже нет или она в корзине)
        if not same_dir and old_here:
            try:
                item = ctx.trash.move_to_trash(storage, rel_dir, reason=RENAME_REASON)
                ctx.log(job.id, f"Прежняя папка «{rel_dir}» перенесена в корзину ({item.id}).")
            except (StorageError, TrashError, OSError) as e:
                removed = None
                ctx.log(job.id, f"Предупреждение: прежняя папка «{rel_dir}» не перенесена в корзину: {e}")
        old = ctx.library.get(storage.target_id, rel_dir)
        own_id = old.own_song_id if old else None
        if removed:
            ctx.library.remove(storage.target_id, removed)
        _index(ctx, job, storage, new_rel, own_id)
        self._rename_own(ctx, job, own_id, rel_dir, new_rel)
        self._rename_tags(ctx, job, old)
        remove_tree(ctx.paths.job(rel_dir, job.id))
        _prune_song_dir(ctx, rel_dir)
        _done(ctx, job)

    @staticmethod
    def _unavailable(ctx: JobContext, job: Job, name: str, e: Exception, note: str = "") -> None:
        """Хранилище не отвечает: ждать (``wait``; недописанную папку повтор уберёт сам) или упасть."""
        _reset(ctx, job.params.get("target_id"))
        if job.params.get("wait"):
            wait_retry(ctx, job, f"Ждёт хранилище «{name}»",
                       f"Хранилище «{name}» недоступно: {e}{note}; повтор через минуту.")
            return
        raise JobFailed("storage", f"Хранилище «{name}» недоступно: {e}{note}") from None

    @staticmethod
    def _publish(ctx: JobContext, job: Job, storage: Storage, result: Path, trash_first: bool) -> None:
        """Выкладка ``result`` в ``new_rel_dir``. ``trash_first`` (та же папка без учёта регистра) —
        сначала старая в корзину, при сбое — откат; при сбое выкладки недописанная новая папка
        удаляется (её до задания не было). Сбой корзины при живом хранилище — ошибка, не ожидание."""
        p = job.params
        rel_dir, new_rel = p["rel_dir"], p["new_rel_dir"]
        item = None
        if trash_first:
            try:
                item = ctx.trash.move_to_trash(storage, rel_dir, reason=RENAME_REASON)
            except (StorageError, TrashError, OSError) as e:
                if not _alive(storage):
                    raise _Retry(e) from None
                raise JobFailed("trash", f"Прежнюю папку «{rel_dir}» не удалось перенести в корзину: {e}") from None
            ctx.log(job.id, f"Прежняя папка «{rel_dir}» перенесена в корзину ({item.id}).")
        try:
            written = storage.upload_dir(result, new_rel)
        except (StorageError, OSError) as e:
            note = ""
            try:
                if storage.exists(new_rel):
                    storage.delete_dir(new_rel)  # недописанная — до задания её не было
                if item is not None:
                    ctx.trash.restore(storage, item.id)
                    ctx.log(job.id, "Прежняя папка возвращена на место.")
            except (StorageError, TrashError, OSError) as e2:
                note = (f"; прежняя папка осталась в корзине ({e2})" if item is not None
                        else f"; недописанная папка «{new_rel}» не удалена ({e2})")
            raise _Retry(e, note) from None
        ctx.log(job.id, f"Выложено в «{storage.label}»: {new_rel} ({len(written)} файлов).")

    @classmethod
    def _build(cls, ctx: JobContext, job: Job, in_dir: Path) -> tuple[Path, str]:
        """``jobs/<id>/result/`` и новое имя ``.txt`` (по ``naming.rename_plan``); сбой диска — ``JobFailed``."""
        try:
            return cls._build_files(ctx, job, in_dir)
        except OSError as e:
            raise JobFailed("prepare", f"Не удалось собрать папку под новым именем: {e}") from None

    @staticmethod
    def _build_files(ctx: JobContext, job: Job, in_dir: Path) -> tuple[Path, str]:
        """Файлы ``in/`` под новыми именами (жёсткие ссылки), ``.txt`` переписан."""
        p = job.params
        artist, title = p["artist"], p["title"]
        txt_name = p.get("txt_name") or ""
        names = sorted(f.name for f in in_dir.iterdir() if f.is_file())
        plan = naming.rename_plan(names, naming.rename_bases(p["rel_dir"], job.artist, job.title),
                                  naming.base_name(artist, title), fallback=[PurePosixPath(txt_name).stem])
        if plan.get(txt_name) is None:
            raise JobFailed("source", f"В папке песни нет «{txt_name}»")
        seen: dict[str, str] = {}
        for old, new in plan.items():  # SMB/Windows не различают регистр — сравнение без него
            other = seen.setdefault(new.casefold(), old)
            if other != old:
                raise JobFailed("input", f"Файлы «{other}» и «{old}» получат одно имя «{new}» — "
                                         "переименуйте или уберите лишний файл вручную")
        result = ctx.paths.job(p["rel_dir"], job.id) / "result"
        shutil.rmtree(result, ignore_errors=True)
        result.mkdir(parents=True)
        for sub in in_dir.iterdir():
            if sub.is_dir():
                shutil.copytree(sub, result / sub.name)
        for old, new in plan.items():
            if old == txt_name:
                try:
                    data = rename_txt((in_dir / old).read_bytes(), artist, title, plan)
                except ValueError:
                    raise JobFailed("input", f"Имя «{artist} — {title}» нельзя записать в кодировке "
                                             f"файла «{txt_name}» — уберите неподдерживаемые символы") from None
                (result / new).write_bytes(data)
                continue
            try:
                os.link(in_dir / old, result / new)  # тот же том: без второй копии видео
            except FileExistsError:  # имя занято вложенной папкой — молча не перезаписывать
                raise JobFailed("input", f"Имя «{new}» в папке песни уже занято") from None
            except OSError:
                shutil.copy2(in_dir / old, result / new)
        changed = sum(1 for o, n in plan.items() if o != n)
        ctx.log(job.id, f"Новое имя: {p['new_rel_dir']} (переименовано файлов: {changed}).")
        return result, plan[txt_name]

    @staticmethod
    def _rename_own(ctx: JobContext, job: Job, own_id: str | None, rel_dir: str, new_rel: str) -> None:
        """Своя песня: строка ``songs`` и исходники ``songs/<rel_dir>/source`` — на новое имя
        (один раз: уже перенесённую заданием другой копии не трогает)."""
        own = ctx.songs.get(own_id) if own_id else ctx.songs.by_rel_dir(rel_dir)
        if own is None or own.rel_dir == new_rel:
            return
        other = ctx.songs.by_rel_dir(new_rel)
        if other is not None and other.id != own.id:
            ctx.log(job.id, f"Предупреждение: исходники не перенесены — под именем «{new_rel}» уже есть другая своя песня")
            return
        p = job.params
        try:
            src, dst = ctx.paths.source(own.rel_dir), ctx.paths.source(new_rel)
            if src.is_dir() and src != dst:
                if dst.exists():  # чужие исходники — не трогать никогда
                    ctx.log(job.id, f"Предупреждение: исходники не перенесены — папка «{new_rel}/source» "
                                    "в томе data уже занята; они остались под прежним именем")
                    return
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                _prune_song_dir(ctx, own.rel_dir)
            ctx.songs.rename(own.id, rel_dir=new_rel, artist=p["artist"], title=p["title"])
            ctx.log(job.id, "Исходники песни перенесены под новое имя.")
        except Exception as e:  # noqa: BLE001 — песня уже переименована в хранилище
            ctx.log(job.id, f"Предупреждение: исходники песни не перенесены: {e}")

    @staticmethod
    def _rename_tags(ctx: JobContext, job: Job, old) -> None:
        artist, title = (old.artist, old.title) if old else (job.artist, job.title)
        old_key = naming.song_tag_key(artist, title)
        new_key = naming.song_tag_key(job.params["artist"], job.params["title"])
        try:
            ctx.tags.copy_key(old_key, new_key)
            if old_key != new_key and not ctx.library.copies(artist, title):
                ctx.tags.drop_key(old_key)  # переименована последняя копия
        except Exception as e:  # noqa: BLE001
            ctx.log(job.id, f"Предупреждение: теги песни не перенесены: {e}")


def _prune_song_dir(ctx: JobContext, rel_dir: str) -> None:
    """Пустые папки песни и исполнителя в томе data — убрать (только пустые)."""
    try:
        d = ctx.paths.song_at(rel_dir)
    except ValueError:
        return
    songs_root = ctx.paths.root / "songs"
    for path in (d / "jobs", d, d.parent):
        if path == songs_root:
            break
        try:
            path.rmdir()
        except OSError:
            pass


# library-tools 09 — зеркало: модуль берёт отсюда помощники, поэтому подключается в конце
from .mirror import MirrorHandler  # noqa: E402
# library-tools 08 — звук по ссылке #VIDEO и проверка библиотеки (модули берут помощники отсюда)
from .audiofix import AudioHandler  # noqa: E402
# library-tools 07 — обложка и фон (модуль берёт помощники отсюда внутри функций)
from .artwork import ArtworkHandler  # noqa: E402
from .libcheck import LibCheckHandler  # noqa: E402

HANDLERS: dict[str, Handler] = {
    "generate": GenerateHandler(),
    "instrumental": InstrumentalHandler(),
    "import": ImportHandler(),
    "publish": PublishHandler(),
    "video": VideoHandler(),
    "copy": CopyHandler(),
    "rename": RenameHandler(),
    "mirror": MirrorHandler(),  # library-tools 09
    "artwork": ArtworkHandler(),  # library-tools 07
    "audio": AudioHandler(),  # library-tools 08
    "libcheck": LibCheckHandler(),  # library-tools 08
}
