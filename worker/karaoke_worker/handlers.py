"""Обработчики заданий: generate, instrumental, publish (Решения §2–§6, истории 30–33, 43–47)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Protocol

from karaoke_core import naming, postprocess, ultrastar
from karaoke_core.db import Job, now
from karaoke_core.paths import INPUT_AUDIO, INPUT_PARAMS
from karaoke_core.storage import Storage, StorageError
from karaoke_core.trash import TrashError

from .base import JobContext, JobFailed, remove_tree
from .progress import PUBLISH, STAGE_POSTPROCESS, STAGE_PREPARE, ProgressTracker

__all__ = ["Handler", "GenerateHandler", "InstrumentalHandler", "PublishHandler", "HANDLERS",
           "prepare_lyrics", "ultrasinger_args", "audio_only_copy"]



class Handler(Protocol):
    needs_gpu: bool

    def run(self, job: Job, ctx: JobContext) -> None: ...


def prepare_lyrics(text: str) -> str:
    """Текст для ``--lyrics``: без BOM, переводы строк LF. Позже — раскрытие [Припев] (R29)."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return text.strip("\n") + "\n" if text.strip() else ""


def ultrasinger_args(params: dict, in_mp3: Path, out_dir: Path, lyrics: Path | None,
                     env: dict | None = None) -> list[str]:
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


def _storage(ctx: JobContext) -> Storage:
    try:
        return ctx.storage()
    except StorageError as e:
        ctx.reset_storage()
        raise JobFailed("storage", f"Папка результата недоступна: {e}") from None


def _start_publish(ctx: JobContext, job: Job) -> None:
    ctx.check_cancel(job.id, force=True)
    ctx.jobs.update(job.id, state="publishing", stage=PUBLISH[0], percent=PUBLISH[1])
    ctx.log(job.id, "Выкладка в папку результата…")


def _publish_error(ctx: JobContext, e: Exception, note: str = "") -> JobFailed:
    ctx.reset_storage()
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
    try:
        inputs = src.params.get("inputs") or {}
        in_dir = ctx.paths.abs(inputs["dir"]) if inputs.get("dir") else ctx.paths.job_in(_song_rel_dir(src), src.id)
        source = ctx.paths.source(rel_dir)
        tmp = source.with_name("source.new")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        if in_dir.is_dir():
            for f in in_dir.iterdir():
                if f.is_file():
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


def publish_song(ctx: JobContext, job: Job, src: Job) -> None:
    """Выложить результат generate-задания ``src`` (оно же ``job`` или источник «Выложить повторно»)."""
    rel_dir = _song_rel_dir(src)
    job_dir = ctx.paths.job(rel_dir, src.id)
    result = job_dir / "result"
    if not result.is_dir():
        raise JobFailed("publish", "ошибка выкладки: результат задания не найден в томе")
    _start_publish(ctx, job)
    p = src.params
    replaced = p.get("replace_rel_dir") if p.get("replace") else None
    item = None
    try:
        storage = ctx.storage()
        old_here = bool(replaced) and p.get("target_id") in (None, storage.target_id) and storage.exists(replaced)
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
        raise _publish_error(ctx, e, note) from None
    ctx.log(job.id, f"Выложено в «{storage.label}»: {rel_dir} ({len(written)} файлов).")
    if old_here and replaced != rel_dir:
        # другая папка: сначала выложена новая, теперь старая — в корзину
        try:
            item = ctx.trash.move_to_trash(storage, replaced, reason="заменена новой версией")
            ctx.log(job.id, f"Прежняя версия «{replaced}» перенесена в корзину ({item.id}).")
        except (StorageError, TrashError, OSError) as e:
            ctx.log(job.id, f"Предупреждение: прежняя версия «{replaced}» не перенесена в корзину: {e}")
            replaced = None
    debug = job_dir / "debug"
    if debug.is_dir():  # отладка выравнивания — в папку песни тома (Решения §3)
        dest = ctx.paths.song_at(rel_dir) / "debug"
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(debug), str(dest))
    own_id = _save_sources(ctx, job, src, rel_dir, replaced)
    _index(ctx, job, storage, rel_dir, own_id, removed=replaced)
    remove_tree(job_dir)
    _done(ctx, job)


class GenerateHandler:
    needs_gpu = True

    def run(self, job: Job, ctx: JobContext) -> None:
        p = job.params
        rel_dir = _song_rel_dir(job)
        job_dir = ctx.paths.job(rel_dir, job.id)
        inputs = p.get("inputs") or {}
        in_dir = ctx.paths.abs(inputs["dir"]) if inputs.get("dir") else ctx.paths.job_in(rel_dir, job.id)
        audio = ctx.paths.abs(inputs["audio"]) if inputs.get("audio") else in_dir / INPUT_AUDIO
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

        cmd = ctx.ultrasinger_cmd() + ultrasinger_args(p, us_in, out, lyrics, dict(ctx.env))
        tail = ctx.run_command(job.id, cmd, tracker=tracker, cwd=ctx.ultrasinger_cwd())
        folders = [d for d in out.iterdir() if d.is_dir()]
        if len(folders) != 1:
            what = "нет выходной папки" if not folders else f"выходных папок {len(folders)}, ожидалась одна"
            last = "\n".join(tail[-5:])
            raise JobFailed("no_output", f"UltraSinger не создал результат ({what}) — проверьте модель "
                                         f"и параметры{chr(10) * 2 + 'Последние строки лога:' + chr(10) + last if last else ''}")
        ctx.check_cancel(job.id, force=True)

        ctx.progress(job.id, tracker.set(*STAGE_POSTPROCESS))
        cover = ctx.paths.abs(inputs["cover"]) if inputs.get("cover") else None
        try:
            fin = postprocess.finalize(folders[0], job.artist, job.title,
                                       cover if cover is not None and cover.is_file() else None,
                                       dest_dir=job_dir / "result")
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
        storage = ctx.storage()
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
        raise _publish_error(ctx, e) from None
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
        storage = _storage(ctx)
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
            ctx.reset_storage()
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


# ============================================================================ publish

class PublishHandler:
    """«Выложить повторно»: результат упавшего на выкладке задания (без GPU)."""
    needs_gpu = False

    def run(self, job: Job, ctx: JobContext) -> None:
        src = ctx.jobs.get(job.params.get("source_job_id") or job.parent_id or 0)
        if src is None:
            raise JobFailed("input", "Исходное задание для выкладки не найдено")
        if src.type == "generate":
            publish_song(ctx, job, src)
        elif src.type == "instrumental":
            publish_instrumental(ctx, job, src)
        else:
            raise JobFailed("input", f"Задание типа «{src.type}» нельзя выложить повторно")


HANDLERS: dict[str, Handler] = {
    "generate": GenerateHandler(),
    "instrumental": InstrumentalHandler(),
    "publish": PublishHandler(),
}
