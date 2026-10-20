"""Редактор строк (G05.1): ноты структурой и обратное применение правок к модели .txt.

Разрешено только менять текст слогов, склеивать/разбивать строки и удалять ноты.
Всё, что не менялось, записывается байт в байт (строки модели хранят исходный текст).
"""

from __future__ import annotations

from pydantic import BaseModel

from karaoke_core import ultrastar
from karaoke_core.ultrastar import End, LineBreak, Note

from .context import ApiError

DUET_REASON = "Дуэты редактор пока не поддерживает — только просмотр"
RELATIVE_REASON = "Файлы с #RELATIVE редактор пока не поддерживает — только просмотр"
TIMING_ERROR = "Тайминги и высоты нот менять нельзя — только текст"


class NoteIn(BaseModel):
    type: str
    start: int
    length: int
    pitch: int
    text: str = ""


class LineIn(BaseModel):
    break_beat: int | None = None
    notes: list[NoteIn]


class NotesIn(BaseModel):
    editable: bool | None = None
    reason: str | None = None
    bpm: float | None = None
    gap: float | None = None
    headers: list[list[str]] = []  # только для чтения: заголовки не меняются
    lines: list[LineIn]


def _num(value: str | None) -> float | None:
    try:
        v = ultrastar.number(value, None)
    except ValueError:
        return None
    return int(v) if v is not None and v.is_integer() else v


def read_only_reason(song: ultrastar.Song) -> str | None:
    if song.is_duet:
        return DUET_REASON
    if song.relative:
        return RELATIVE_REASON
    return None


def notes_payload(song: ultrastar.Song) -> dict:
    reason = read_only_reason(song)
    out = {"editable": reason is None, "bpm": _num(song.header("BPM")), "gap": _num(song.header("GAP")),
           "headers": [[k, v] for k, v in song.header_items()],
           "lines": [{"break_beat": ln["break"].beat if ln["break"] is not None else None,
                      **({"player": ln["player"]} if ln["player"] is not None else {}),
                      "notes": [{"type": n.type, "start": n.start, "length": n.length,
                                 "pitch": n.pitch, "text": n.text} for n in ln["notes"]]}
                     for ln in song.lines()]}
    if reason:
        out["reason"] = reason
    return out


def apply_notes(song: ultrastar.Song, body: NotesIn) -> None:
    """Применить правки строк к модели ``song`` (на месте). Ошибка → ApiError(400)."""
    originals = song.notes()
    kept: dict[int, str] = {}  # id(исходной ноты) → новый текст
    break_before: dict[int, int | None] = {}  # id(первой ноты строки) → бит разрыва
    i = 0
    prev_last: Note | None = None
    for li, line in enumerate(body.lines):
        for ni, n in enumerate(line.notes):
            while i < len(originals) and (originals[i].type, originals[i].start, originals[i].length,
                                          originals[i].pitch) != (n.type, n.start, n.length, n.pitch):
                i += 1
            if i == len(originals):
                raise ApiError(400, TIMING_ERROR)
            orig = originals[i]
            i += 1
            kept[id(orig)] = n.text
            if ni == 0 and li > 0 and prev_last is not None:
                beat = body.lines[li - 1].break_beat
                break_before[id(orig)] = beat if beat is not None else prev_last.end
            prev_last = orig
    if not kept:
        raise ApiError(400, "В песне должна остаться хотя бы одна нота")

    out: list = []
    pending: LineBreak | None = None
    held: list = []  # строки между разрывом и следующей нотой
    for item in song.body:
        if isinstance(item, Note):
            if id(item) not in kept:
                continue
            if id(item) in break_before:
                beat = break_before[id(item)]
                if pending is not None and pending.beat != beat:
                    pending.beat = beat
                    pending.beat2 = None
                out.append(pending or LineBreak(beat=beat, eol=song.newline))
            out.extend(held)
            pending, held = None, []
            if item.text != kept[id(item)]:
                item.text = kept[id(item)]
            out.append(item)
        elif isinstance(item, LineBreak):
            pending = item
        elif isinstance(item, End):
            out.extend(held)
            pending, held = None, []
            out.append(item)
        elif pending is not None:
            held.append(item)
        else:
            out.append(item)
    out.extend(held)
    song.body = out
