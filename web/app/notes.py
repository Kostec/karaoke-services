"""Редактор нот: ноты структурой и обратное применение правок к модели .txt.

У каждой ноты ``id`` — её порядковый номер в исходном файле. PUT принимает новые
тайминги, высоты, типы, текст, удалённые и новые (``id: null``) ноты, границы строк
и ``gap``. Всё, что не менялось, записывается байт в байт (строки модели хранят
исходный текст); неразобранные строки тела остаются перед своей нотой.
"""

from __future__ import annotations

from pydantic import BaseModel

from karaoke_core import ultrastar
from karaoke_core.ultrastar import End, LineBreak, Note

from .context import ApiError

DUET_REASON = "Дуэты редактор пока не поддерживает — только просмотр"
RELATIVE_REASON = "Файлы с #RELATIVE редактор пока не поддерживает — только просмотр"
NO_BPM_REASON = "В песне нет #BPM — редактор только для просмотра"


class NoteIn(BaseModel):
    id: int | None = None  # порядковый номер ноты в исходном файле; None — новая нота
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
    bpm = _num(song.header("BPM"))
    if bpm is None or bpm <= 0:
        return NO_BPM_REASON
    return None


def notes_payload(song: ultrastar.Song) -> dict:
    reason = read_only_reason(song)
    ids = {id(n): i for i, n in enumerate(song.notes())}
    out = {"editable": reason is None, "bpm": _num(song.header("BPM")), "gap": _num(song.header("GAP")),
           "headers": [[k, v] for k, v in song.header_items()],
           "lines": [{"break_beat": ln["break"].beat if ln["break"] is not None else None,
                      **({"player": ln["player"]} if ln["player"] is not None else {}),
                      "notes": [{"id": ids[id(n)], "type": n.type, "start": n.start, "length": n.length,
                                 "pitch": n.pitch, "text": n.text} for n in ln["notes"]]}
                     for ln in song.lines()]}
    if reason:
        out["reason"] = reason
    return out


def _fmt_gap(value: float) -> str:
    """#GAP: не больше 3 знаков после точки, без хвостовых нулей; целое — без «.0»."""
    text = f"{round(float(value), 3):.3f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _flatten(body: NotesIn) -> list[tuple[int, NoteIn, int | None]]:
    """Ноты тела запроса подряд: (номер строки с 1, нота, бит разрыва перед ней или None)."""
    out: list[tuple[int, NoteIn, int | None]] = []
    prev_break: int | None = None
    for li, line in enumerate(body.lines, start=1):
        for ni, n in enumerate(line.notes):
            if ni == 0 and out:
                prev = out[-1][1]
                out.append((li, n, prev_break if prev_break is not None else prev.start + prev.length))
            else:
                out.append((li, n, None))
        if line.notes:
            prev_break = line.break_beat
    return out


def _validate(flat: list[tuple[int, NoteIn, int | None]], body: NotesIn) -> None:
    """Проверки PUT (спецификация §14); ошибка — ApiError(400) с местом по-русски."""
    prev: tuple[int, NoteIn] | None = None
    for li, n, br in flat:
        where = f"строка {li}, слог «{n.text.strip()}»"
        if n.type not in ultrastar.NOTE_TYPES:
            raise ApiError(400, f"Неизвестный тип ноты «{n.type}»: {where}")
        if n.start < 0:
            raise ApiError(400, f"Начало ноты раньше бита 0: {where}")
        if n.length < 1:
            raise ApiError(400, f"Длина ноты — не меньше 1 бита: {where}")
        if not -40 <= n.pitch <= 100:
            raise ApiError(400, f"Высота ноты — от −40 до 100: {where}")
        if "\n" in n.text or "\r" in n.text:
            raise ApiError(400, f"В слоге не может быть перевода строки: строка {li}")
        if prev is not None:
            p_li, p = prev
            p_end = p.start + p.length
            if n.start < p_end:
                raise ApiError(400, f"Ноты перекрываются: {where}")
            if br is not None and not p_end <= br <= n.start:
                raise ApiError(400, f"Разрыв строки {p_li} должен стоять между концом её последней ноты "
                                    f"и началом строки {li}")
        prev = (li, n)
    if body.gap is not None and body.gap < 0:
        raise ApiError(400, "Раньше начала трека сдвигать некуда: #GAP не может быть меньше 0")


def apply_notes(song: ultrastar.Song, body: NotesIn) -> None:
    """Применить правки нот к модели ``song`` (на месте). Ошибка → ApiError(400).

    Ноты сопоставляются с исходными по ``id`` (порядковый номер в файле); у
    неизменённых нот и прочих строк файла сохраняется исходный текст.
    """
    flat = _flatten(body)
    if not flat:
        raise ApiError(400, "В песне должна остаться хотя бы одна нота")
    _validate(flat, body)
    originals = song.notes()
    used: set[int] = set()
    for _li, n, _br in flat:
        if n.id is not None:
            if not 0 <= n.id < len(originals):
                raise ApiError(400, f"Нота с id {n.id} не найдена в файле")
            if n.id in used:
                raise ApiError(400, f"Нота с id {n.id} встречается дважды")
            used.add(n.id)

    # Исходное тело: что стоит перед каждой исходной нотой (до разрыва, разрыв, после него).
    index = {id(n): i for i, n in enumerate(originals)}
    before: dict[int, tuple[list, LineBreak | None, list]] = {}
    pre: list = []
    brk: LineBreak | None = None
    post: list = []
    tail: list = []  # после последней ноты и до E включительно — и всё, что после E
    seen_note = False
    ended = False
    for item in song.body:
        if ended:
            tail.append(item)
        elif isinstance(item, Note):
            before[index[id(item)]] = (pre, brk, post)
            pre, brk, post, seen_note = [], None, [], True
        elif isinstance(item, End):
            tail.extend([*pre, *([brk] if brk else []), *post, item])
            pre, brk, post, ended = [], None, [], True
        elif isinstance(item, LineBreak) and seen_note:
            if brk is not None:
                pre.extend([brk, *post])
                post = []
            brk = item
        elif brk is not None:
            post.append(item)
        else:
            pre.append(item)
    if not ended:
        tail = [*pre, *([brk] if brk else []), *post]

    # Строки удалённых нот переходят к следующей уцелевшей (в порядке файла).
    carry: list = []
    for i in range(len(originals)):
        p, b, q = before[i]
        if i in used:
            before[i] = (carry + p, b, q)
            carry = []
        else:
            carry += p + q
    tail = carry + tail

    out: list = []
    for _li, n, br in flat:
        if n.id is not None:
            p, old_break, q = before[n.id]
            note = originals[n.id]
            note.type, note.start, note.length, note.pitch, note.text = n.type, n.start, n.length, n.pitch, n.text
        else:
            p, old_break, q = [], None, []
            note = Note(type=n.type, start=n.start, length=n.length, pitch=n.pitch, text=n.text,
                        eol=song.newline)
        out.extend(p)
        if br is not None:
            if old_break is not None:
                if old_break.beat != br:
                    old_break.beat, old_break.beat2 = br, None
                out.append(old_break)
            else:
                out.append(LineBreak(beat=br, eol=song.newline))
        out.extend(q)
        out.append(note)
    out.extend(tail)
    for item in out[:-1]:
        if not item.eol:
            item.eol = song.newline
    song.body = out

    if body.gap is not None:
        current = _num(song.header("GAP"))
        if current is None or _fmt_gap(current) != _fmt_gap(body.gap):
            song.set_header("GAP", _fmt_gap(body.gap))
