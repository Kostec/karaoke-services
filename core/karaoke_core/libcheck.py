"""Проверка библиотеки (истории 34–39): снимок песни хранилища и находки по снимкам.

Сбор снимков (чтение хранилищ) — задание ``libcheck`` воркера, здесь — чистые правила:
какие находки (``no_audio``, ``no_cover``, ``video_missing``, ``encoding``, ``duplicate``,
``diverged``) и какие исправления у каждой (``fix`` — основное, ``fixes`` — все варианты).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from . import naming, songpack, ultrastar
from .db import song_id_for
from .storage.base import PART_SUFFIX, Storage, SongEntry
from .ultrastar import EncodingFix

__all__ = ["KINDS", "SongScan", "scan_song", "audio_link", "finding_id", "find_problems", "make_report",
           "NOT_GUESSED"]

KINDS = ("no_audio", "no_cover", "video_missing", "encoding", "duplicate", "diverged")
NOT_GUESSED = "Не удалось угадать кодировку"
DIFF_NAMES_MAX = 5  # сколько имён файлов перечислять в подробностях расхождения
_YOUTUBE_RE = re.compile(r"^https?://([a-z0-9-]+\.)*(youtube\.com|youtu\.be)/", re.I)


@dataclass
class SongScan:
    """Снимок песни одного хранилища для проверки: что сказано в ``.txt`` и что лежит в папке."""
    target_id: str
    rel_dir: str
    txt_name: str
    artist: str
    title: str
    audio: str | None  # файл звука есть в папке (имя), иначе None
    cover: str | None
    audio_header: str = ""  # #AUDIO, иначе #MP3 — как в файле
    cover_header: str = ""
    video_header: str = ""  # #VIDEO как есть (имя файла или ссылка)
    video_file: str | None = None  # видеофайл из #VIDEO, если он есть в папке
    files: dict[str, int] = field(default_factory=dict)  # {путь внутри папки: байты}
    encoding: EncodingFix | None = None

    @property
    def song_id(self) -> str:
        return song_id_for(self.target_id, self.rel_dir)


def scan_song(storage: Storage, entry: SongEntry) -> SongScan:
    """Снимок песни: заголовки ``.txt``, кодировка, размеры файлов папки (ошибки хранилища — наружу)."""
    data = storage.read(f"{entry.rel_dir}/{entry.txt_name}")
    song = ultrastar.parse(data)

    def header(key: str) -> str:
        return (song.header(key) or "").strip()

    files = {k: v for k, v in storage.sizes(entry.rel_dir).items()
             if not k.endswith(PART_SUFFIX) and not k.rsplit("/", 1)[-1].startswith(".")}
    return SongScan(target_id=storage.target_id, rel_dir=entry.rel_dir, txt_name=entry.txt_name,
                    artist=entry.artist, title=entry.title, audio=entry.audio, cover=entry.cover,
                    audio_header=header("AUDIO") or header("MP3"), cover_header=header("COVER"),
                    video_header=header("VIDEO"), video_file=entry.video, files=files,
                    encoding=ultrastar.encoding_problem(data))


def audio_link(video_header: str | None) -> str | None:
    """Ссылка YouTube для звука из ``#VIDEO`` (usdb ``a=`` раньше ``v=``, либо URL/ID целиком);
    имя видеофайла и не-YouTube ссылки — ``None``. Одно правило для веба и проверки."""
    urls, _cover = songpack.youtube_links(video_header)
    return next((u for u in urls if _YOUTUBE_RE.match(u)), None)


def finding_id(kind: str, song_id: str, other: str = "") -> str:
    """Стабильный id находки: одна и та же проблема в следующей проверке — тот же id."""
    return hashlib.sha1(f"{kind}\n{song_id}\n{other}".encode("utf-8")).hexdigest()[:12]


def _finding(kind: str, s: SongScan, detail: str, fixes: list[dict], other: SongScan | None = None,
             **extra) -> dict:
    out = {"id": finding_id(kind, s.song_id, other.song_id if other else ""), "kind": kind,
           "target_id": s.target_id, "song_id": s.song_id, "artist": s.artist, "title": s.title,
           "rel_dir": s.rel_dir, "detail": detail, "fix": fixes[0], "fixes": fixes, **extra}
    if other is not None:
        out["other"] = {"target_id": other.target_id, "song_id": other.song_id, "artist": other.artist,
                        "title": other.title, "rel_dir": other.rel_dir}
    return out


def _key(s: SongScan) -> str:
    return naming.song_tag_key(s.artist, s.title)


def _song_findings(s: SongScan, copies: list[SongScan]) -> list[dict]:
    """Находки одной песни: звук, обложка, видеофайл, кодировка."""
    out = []
    if not s.audio:
        fixes = [{"action": "copy_from", "from_target": c.target_id, "from_song_id": c.song_id}
                 for c in copies if c.target_id != s.target_id and c.audio]
        if audio_link(s.video_header):
            fixes.append({"action": "audio_from_video"})
        fixes.append({"action": "trash"})
        detail = (f"Нет файла звука «{s.audio_header}»" if s.audio_header
                  else "В песне не указан звук (#AUDIO/#MP3)")
        out.append(_finding("no_audio", s, detail, fixes))
    if not s.cover:
        detail = f"Нет файла обложки «{s.cover_header}»" if s.cover_header else "У песни нет обложки"
        out.append(_finding("no_cover", s, detail, [{"action": "cover_search"}]))
    video = naming.video_file_name(s.video_header)
    if video and not s.video_file:
        out.append(_finding("video_missing", s, f"Нет видеофайла «{video}» из #VIDEO", [{"action": "video_remove"}]))
    if s.encoding is not None:
        e = s.encoding
        fix = {"action": "encoding"}
        if not e.fixed_text:
            fix["disabled"] = NOT_GUESSED
        detail = f"{e.preview_before} → {e.preview_after}" if e.fixed_text else f"{e.preview_before} ({NOT_GUESSED.lower()})"
        out.append(_finding("encoding", s, detail, [fix], before=e.preview_before, after=e.preview_after,
                            encoding_kind=e.kind))
    return out


def _duplicates(scans: list[SongScan], names: dict[str, str]) -> list[dict]:
    """Пары песен одного хранилища с одинаковым грубым ключом (разное написание)."""
    groups: dict[tuple[str, str], list[SongScan]] = {}
    for s in scans:
        groups.setdefault((s.target_id, naming.rough_key(s.artist, s.title)), []).append(s)
    out = []
    for group in groups.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                fixes = [{"action": "keep_this", "song_id": a.song_id, "trash_song_id": b.song_id},
                         {"action": "keep_this", "song_id": b.song_id, "trash_song_id": a.song_id}]
                detail = f"Похожа на «{b.artist} — {b.title}» ({b.rel_dir})"
                out.append(_finding("duplicate", a, detail, fixes, other=b))
    return out


def _folded(files: dict[str, int]) -> dict[str, tuple[str, int]]:
    return {k.casefold(): (k, v) for k, v in files.items()}


def _names(items: list[str]) -> str:
    shown = ", ".join(items[:DIFF_NAMES_MAX])
    return shown + (f" и ещё {len(items) - DIFF_NAMES_MAX}" if len(items) > DIFF_NAMES_MAX else "")


def _diff(a: SongScan, b: SongScan, names: dict[str, str]) -> str | None:
    """Чем различаются копии (набор файлов и размеры, без учёта регистра имён); одинаковые — None."""
    fa, fb = _folded(a.files), _folded(b.files)
    only_a = sorted(fa[k][0] for k in fa.keys() - fb.keys())
    only_b = sorted(fb[k][0] for k in fb.keys() - fa.keys())
    sizes = sorted(f"{fa[k][0]} ({fa[k][1]} и {fb[k][1]} байт)" for k in fa.keys() & fb.keys()
                   if fa[k][1] != fb[k][1])
    parts = []
    if only_a:
        parts.append(f"только в «{names.get(a.target_id, a.target_id)}»: {_names(only_a)}")
    if only_b:
        parts.append(f"только в «{names.get(b.target_id, b.target_id)}»: {_names(only_b)}")
    if sizes:
        parts.append(f"другой размер: {_names(sizes)}")
    if not parts:
        return None
    text = "; ".join(parts)
    return text[0].upper() + text[1:]


def _diverged(scans: list[SongScan], names: dict[str, str]) -> list[dict]:
    """Пары копий одной песни (``match_key``) в разных хранилищах с разными файлами."""
    groups: dict[str, list[SongScan]] = {}
    for s in scans:
        groups.setdefault(_key(s), []).append(s)
    out = []
    for group in groups.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a.target_id == b.target_id:
                    continue  # одно хранилище — это дубль, а не расхождение
                detail = _diff(a, b, names)
                if detail is None:
                    continue
                fixes = [{"action": "make_like", "song_id": a.song_id, "from_target": b.target_id,
                          "from_song_id": b.song_id},
                         {"action": "make_like", "song_id": b.song_id, "from_target": a.target_id,
                          "from_song_id": a.song_id}]
                out.append(_finding("diverged", a, detail, fixes, other=b))
    return out


def find_problems(scans: list[SongScan], names: dict[str, str]) -> list[dict]:
    """Находки по снимкам проверенных хранилищ (``names`` — id хранилища → имя для текста).
    Порядок снимков задаёт порядок находок; первая песня пары — та, что раньше."""
    copies: dict[str, list[SongScan]] = {}
    for s in scans:
        copies.setdefault(_key(s), []).append(s)
    out = []
    for s in scans:
        out.extend(_song_findings(s, copies[_key(s)]))
    out.extend(_duplicates(scans, names))
    out.extend(_diverged(scans, names))
    return out


def make_report(*, job_id: int | None, target_ids: list[str], skipped: list[dict], findings: list[dict],
                started_at: str, finished_at: str) -> dict:
    """Отчёт ``reports/libcheck.json`` (interfaces.md «core: отчёт проверки»)."""
    return {"started_at": started_at, "finished_at": finished_at, "job_id": job_id, "target_ids": target_ids,
            "skipped": skipped, "findings": findings}
