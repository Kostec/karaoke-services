"""Редактор нот: ноты структурой и обратное применение правок к модели .txt.

У каждой ноты ``id`` — её порядковый номер в исходном файле. PUT принимает новые
тайминги, высоты, типы, текст, удалённые и новые (``id: null``) ноты, границы строк,
певцов строк дуэта (``player``), имена певцов и ``gap``. Всё, что не менялось,
записывается байт в байт (строки модели хранят исходный текст); неразобранные
строки тела остаются перед своей нотой.
"""

from __future__ import annotations

from pydantic import BaseModel

from karaoke_core import ultrastar
from karaoke_core.ultrastar import End, LineBreak, Note, PlayerMark

from .context import ApiError

MANY_SINGERS_REASON = "В песне больше двух певцов — редактор только для просмотра"
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
    player: int | None = None  # певец строки дуэта (1|2); у соло — нет
    notes: list[NoteIn]


class SingersIn(BaseModel):
    p1: str = ""
    p2: str = ""


class NotesIn(BaseModel):
    editable: bool | None = None
    reason: str | None = None
    duet: bool | None = None  # только для чтения: дуэт ли — решают player строк
    bpm: float | None = None
    gap: float | None = None
    headers: list[list[str]] = []  # только для чтения: заголовки не меняются
    singers: SingersIn | None = None
    lines: list[LineIn]


Flat = list[tuple[int, NoteIn, int | None]]


def _num(value: str | None) -> float | None:
    try:
        v = ultrastar.number(value, None)
    except ValueError:
        return None
    return int(v) if v is not None and v.is_integer() else v


def read_only_reason(song: ultrastar.Song) -> str | None:
    if any(isinstance(x, PlayerMark) and x.player not in (1, 2) for x in song.body):
        return MANY_SINGERS_REASON
    if song.relative:
        return RELATIVE_REASON
    bpm = _num(song.header("BPM"))
    if bpm is None or bpm <= 0:
        return NO_BPM_REASON
    return None


def notes_payload(song: ultrastar.Song) -> dict:
    reason = read_only_reason(song)
    ids = {id(n): i for i, n in enumerate(song.notes())}
    duet = song.is_duet
    p1, p2 = ultrastar.singer_names(song) if duet else ("", "")
    out = {"editable": reason is None, "bpm": _num(song.header("BPM")), "gap": _num(song.header("GAP")),
           "duet": duet, "singers": {"p1": p1, "p2": p2},
           "headers": [[k, v] for k, v in song.header_items()],
           "lines": [{"break_beat": ln["break"].beat if ln["break"] is not None else None,
                      **({"player": ln["player"] or 1} if duet else {}),
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


def _tracks(body: NotesIn) -> list[tuple[int | None, list[LineIn]]]:
    """Партии тела запроса: ``[(None, строки)]`` у соло, ``[(1, …), (2, …)]`` у дуэта.

    Дуэт — если хотя бы у одной строки с нотами певец 2. Если ``player`` есть только
    у части строк или он не 1/2 — ApiError(400).
    """
    if all(line.player is None for line in body.lines):
        return [(None, body.lines)]
    for i, line in enumerate(body.lines, start=1):
        if line.player is None:
            raise ApiError(400, f"Строка {i}: не указан певец (1 или 2)")
        if line.player not in (1, 2):
            raise ApiError(400, f"Строка {i}: певец — 1 или 2, а не {line.player}")
    if not any(line.player == 2 and line.notes for line in body.lines):
        return [(None, body.lines)]
    return [(p, [line for line in body.lines if line.player == p]) for p in (1, 2)]


def _flatten(lines: list[LineIn]) -> Flat:
    """Ноты партии подряд: (номер строки в партии с 1, нота, бит разрыва перед ней или None)."""
    out: Flat = []
    prev_break: int | None = None
    for li, line in enumerate(lines, start=1):
        for ni, n in enumerate(line.notes):
            if ni == 0 and out:
                prev = out[-1][1]
                out.append((li, n, prev_break if prev_break is not None else prev.start + prev.length))
            else:
                out.append((li, n, None))
        if line.notes:
            prev_break = line.break_beat
    return out


def _where(player: int | None, li: int, what: str, text: str | None = None) -> str:
    """Место ошибки: у соло «Что: строка K, слог «x»», у дуэта «Певец N, строка K: что, слог «x»»."""
    syl = f", слог «{text.strip()}»" if text is not None else ""
    if player is None:
        return f"{what}: строка {li}{syl}"
    return f"Певец {player}, строка {li}: {what[0].lower()}{what[1:]}{syl}"


def _validate(player: int | None, flat: Flat) -> None:
    """Проверки PUT внутри партии (спецификация §14); ошибка — ApiError(400) с местом по-русски."""
    prev: tuple[int, NoteIn] | None = None
    for li, n, br in flat:
        if n.type not in ultrastar.NOTE_TYPES:
            raise ApiError(400, _where(player, li, f"Неизвестный тип ноты «{n.type}»", n.text))
        if n.start < 0:
            raise ApiError(400, _where(player, li, "Начало ноты раньше бита 0", n.text))
        if n.length < 1:
            raise ApiError(400, _where(player, li, "Длина ноты — не меньше 1 бита", n.text))
        if not -40 <= n.pitch <= 100:
            raise ApiError(400, _where(player, li, "Высота ноты — от −40 до 100", n.text))
        if "\n" in n.text or "\r" in n.text:
            raise ApiError(400, _where(player, li, "В слоге не может быть перевода строки"))
        if prev is not None:
            p_li, p = prev
            p_end = p.start + p.length
            if n.start < p_end:
                raise ApiError(400, _where(player, li, "Ноты перекрываются", n.text))
            if br is not None and not p_end <= br <= n.start:
                if player is None:
                    raise ApiError(400, f"Разрыв строки {p_li} должен стоять между концом её последней ноты "
                                        f"и началом строки {li}")
                raise ApiError(400, f"Певец {player}, строка {p_li}: разрыв должен стоять между концом "
                                    f"её последней ноты и началом строки {li}")
        prev = (li, n)


def _break_before_p2(lines: list[LineIn]) -> int | None:
    """Разрыв последней строки певца 1 — пишется перед ``P2`` (раскладка «- N, P2»), если задан."""
    with_notes = [(i, ln) for i, ln in enumerate(lines, start=1) if ln.notes]
    if not with_notes or with_notes[-1][1].break_beat is None:
        return None
    li, last = with_notes[-1]
    end = max(n.start + n.length for n in last.notes)
    if last.break_beat < end:
        raise ApiError(400, f"Певец 1, строка {li}: разрыв должен стоять не раньше конца её последней ноты")
    return last.break_beat


def apply_notes(song: ultrastar.Song, body: NotesIn) -> None:
    """Применить правки нот к модели ``song`` (на месте). Ошибка → ApiError(400).

    Ноты сопоставляются с исходными по ``id`` (порядковый номер в файле); у
    неизменённых нот и прочих строк файла сохраняется исходный текст. Дуэт пишется
    блоками ``P1 …``, ``P2 …``; прежние метки ``P`` переиспользуются. Без строк
    певца 2 песня записывается соло: без меток и заголовков имён.
    """
    parts = _tracks(body)
    tracks = [(p, _flatten(lines)) for p, lines in parts]
    duet = parts[0][0] is not None
    if not any(flat for _p, flat in tracks):
        raise ApiError(400, "В песне должна остаться хотя бы одна нота")
    for p, flat in tracks:
        _validate(p, flat)
    if body.gap is not None and body.gap < 0:
        raise ApiError(400, "Раньше начала трека сдвигать некуда: #GAP не может быть меньше 0")
    p2_break = _break_before_p2(parts[0][1]) if duet else None
    originals = song.notes()
    used: set[int] = set()
    for _p, flat in tracks:
        for _li, n, _br in flat:
            if n.id is not None:
                if not 0 <= n.id < len(originals):
                    raise ApiError(400, f"Нота с id {n.id} не найдена в файле")
                if n.id in used:
                    raise ApiError(400, f"Нота с id {n.id} встречается дважды")
                used.add(n.id)

    # Метки певцов файла: переиспользуется первая метка каждого певца, прочие отбрасываются.
    marks: dict[int, PlayerMark] = {}
    for item in song.body:
        if isinstance(item, End):
            break
        if isinstance(item, PlayerMark):
            marks.setdefault(item.player, item)

    def clean(items: list) -> list:
        return [x for x in items if not isinstance(x, PlayerMark)]

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
            before[index[id(item)]] = (clean(pre), brk, clean(post))
            pre, brk, post, seen_note = [], None, [], True
        elif isinstance(item, End):
            tail.extend([*clean(pre), *([brk] if brk else []), *clean(post), item])
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
        tail = clean([*pre, *([brk] if brk else []), *post])

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

    def line_break(old: LineBreak | None, beat: int) -> LineBreak:
        if old is None:
            return LineBreak(beat=beat, eol=song.newline)
        if old.beat != beat:
            old.beat, old.beat2 = beat, None
        return old

    out: list = []
    for player, flat in tracks:
        for k, (_li, n, br) in enumerate(flat):
            if n.id is not None:
                p, old_break, q = before[n.id]
                note = originals[n.id]
                note.type, note.start, note.length, note.pitch, note.text = (
                    n.type, n.start, n.length, n.pitch, n.text)
            else:
                p, old_break, q = [], None, []
                note = Note(type=n.type, start=n.start, length=n.length, pitch=n.pitch, text=n.text,
                            eol=song.newline)
            note.player = player
            out.extend(p)
            if duet and k == 0:
                # Начало партии: разрыв перед ней не пишется — кроме раскладки «- N, P2».
                if player == 2 and p2_break is not None:
                    out.append(line_break(old_break, p2_break))
                out.append(marks.get(player) or PlayerMark(player=player, eol=song.newline))
            elif br is not None:
                out.append(line_break(old_break, br))
            out.extend(q)
            out.append(note)
    out.extend(tail)
    for item in out[:-1]:
        if not item.eol:
            item.eol = song.newline
    song.body = out

    if duet:
        if body.singers is not None:
            names = (body.singers.p1.strip(), body.singers.p2.strip())
            if names != ultrastar.singer_names(song):
                ultrastar.set_singer_names(song, *names)
    else:
        ultrastar.set_singer_names(song, "", "")

    if body.gap is not None:
        current = _num(song.header("GAP"))
        if current is None or _fmt_gap(current) != _fmt_gap(body.gap):
            song.set_header("GAP", _fmt_gap(body.gap))
