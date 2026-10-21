"""Формат UltraStar .txt: разбор, запись байт в байт, точечные правки.

Модель хранит исходный текст каждой строки и её перевод строки. Пока поля
строки не менялись, при записи используется исходный текст — поэтому
``render(parse(b)) == b`` для любого файла. Изменённые строки пишутся
заново в каноническом виде.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar

__all__ = [
    "Song", "Header", "Note", "LineBreak", "PlayerMark", "End", "RawLine",
    "parse", "render", "set_header_line", "fix_zero_length", "beat_to_ms",
    "extract_lyrics", "NOTE_TYPES", "decode", "number", "singer_names", "set_singer_names",
    "set_line_starts",
]

NOTE_TYPES = (":", "*", "F", "R", "G")

_BOM = b"\xef\xbb\xbf"
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+\Z")
_EOL_RE = re.compile(r"(\r\n|\n|\r)\Z")
_HEADER_RE = re.compile(r"^#([^:]*):(.*)\Z", re.S)
_NOTE_RE = re.compile(r"^([:*FRG])\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)(?: (.*))?\Z", re.S)
_BREAK_RE = re.compile(r"^-\s*(-?\d+)(?:\s+(-?\d+))?\s*\Z")
_PLAYER_RE = re.compile(r"^P\s*(\d+)\s*\Z")
_END_RE = re.compile(r"^E\s*\Z")

# Куда вставлять отсутствующий заголовок: после первого найденного соседа.
_INSERT_AFTER = {
    "INSTRUMENTAL": ("VOCALS", "AUDIO", "MP3"),
    "VOCALS": ("AUDIO", "MP3"),
    "AUDIO": ("MP3",),
    "COVER": ("GENRE", "LANGUAGE", "YEAR", "TITLE"),
    "P2": ("P1",),
}


# --------------------------------------------------------------------------- модель

@dataclass(eq=False)
class _Line:
    eol: str = field(default="\n", kw_only=True)
    raw: str | None = field(default=None, kw_only=True, repr=False)
    _snap: tuple | None = field(default=None, kw_only=True, repr=False)

    _SNAP_FIELDS: ClassVar[tuple[str, ...]] = ()

    def _values(self) -> tuple:
        return tuple(getattr(self, f) for f in self._SNAP_FIELDS)

    def _freeze(self) -> None:
        self._snap = self._values()

    def format(self) -> str:  # pragma: no cover - переопределяется
        raise NotImplementedError

    def line(self) -> str:
        if self.raw is not None and self._snap == self._values():
            return self.raw
        return self.format()


@dataclass(eq=False)
class Header(_Line):
    key: str = ""
    value: str = ""
    _SNAP_FIELDS = ("key", "value")

    def format(self) -> str:
        return f"#{self.key}:{self.value}"


@dataclass(eq=False)
class Note(_Line):
    type: str = ":"
    start: int = 0
    length: int = 0
    pitch: int = 0
    text: str = ""
    player: int | None = None
    _SNAP_FIELDS = ("type", "start", "length", "pitch", "text")

    def format(self) -> str:
        return f"{self.type} {self.start} {self.length} {self.pitch} {self.text}"

    @property
    def end(self) -> int:
        return self.start + self.length


@dataclass(eq=False)
class LineBreak(_Line):
    beat: int = 0
    beat2: int | None = None
    _SNAP_FIELDS = ("beat", "beat2")

    def format(self) -> str:
        return f"- {self.beat}" if self.beat2 is None else f"- {self.beat} {self.beat2}"


@dataclass(eq=False)
class PlayerMark(_Line):
    player: int = 1
    _SNAP_FIELDS = ("player",)

    def format(self) -> str:
        return f"P{self.player}"


@dataclass(eq=False)
class End(_Line):
    def format(self) -> str:
        return "E"


@dataclass(eq=False)
class RawLine(_Line):
    """Строка, которую парсер не распознал (пустая, комментарий и т. п.)."""
    content: str = ""
    _SNAP_FIELDS = ("content",)

    def format(self) -> str:
        return self.content


@dataclass(eq=False)
class Song:
    headers: list = field(default_factory=list)  # Header | RawLine
    body: list = field(default_factory=list)  # Note | LineBreak | PlayerMark | End | RawLine
    encoding: str = "utf-8"
    bom: bool = False
    newline: str = "\n"

    # --- заголовки
    def _find(self, key: str) -> Header | None:
        k = key.upper()
        for h in self.headers:
            if isinstance(h, Header) and h.key.upper() == k:
                return h
        return None

    def header(self, key: str, default: str | None = None) -> str | None:
        h = self._find(key)
        return h.value if h is not None else default

    def header_items(self) -> list[tuple[str, str]]:
        return [(h.key, h.value) for h in self.headers if isinstance(h, Header)]

    def set_header(self, key: str, value: str) -> None:
        h = self._find(key)
        if h is not None:
            h.value = value
            return
        keys = [h.key.upper() if isinstance(h, Header) else None for h in self.headers]
        idx = _insert_index(keys, key.upper())
        new = Header(key=key.upper(), value=value, eol=self.newline)
        if idx > 0 and self.headers[idx - 1].eol == "":
            self.headers[idx - 1].eol = self.newline
        self.headers.insert(idx, new)

    def remove_header(self, key: str) -> bool:
        k = key.upper()
        before = len(self.headers)
        self.headers = [h for h in self.headers
                        if not (isinstance(h, Header) and h.key.upper() == k)]
        return len(self.headers) != before

    # --- тело
    def notes(self) -> list[Note]:
        return [x for x in self.body if isinstance(x, Note)]

    @property
    def is_duet(self) -> bool:
        return any(isinstance(x, PlayerMark) for x in self.body)

    @property
    def relative(self) -> bool:
        return (self.header("RELATIVE") or "").strip().lower() in ("yes", "true", "1")

    def lines(self) -> list[dict]:
        """Строки песни: ``[{player, notes:[Note], break: LineBreak|None}]``."""
        out: list[dict] = []
        cur: dict | None = None
        player: int | None = None
        for item in self.body:
            if isinstance(item, PlayerMark):
                player = item.player
                cur = None
            elif isinstance(item, Note):
                if cur is None:
                    cur = {"player": player, "notes": [], "break": None}
                    out.append(cur)
                cur["notes"].append(item)
            elif isinstance(item, LineBreak):
                if cur is None:
                    cur = {"player": player, "notes": [], "break": None}
                    out.append(cur)
                cur["break"] = item
                cur = None
            elif isinstance(item, End):
                break
        return out

    def tracks(self) -> dict[int, list[dict]]:
        """Строки по партиям: ``{1: [строки], 2: [строки]}``; у соло — только ``1``.

        Строки без метки певца (до первого ``P``) относятся к певцу 1.
        """
        out: dict[int, list[dict]] = {}
        for line in self.lines():
            out.setdefault(line["player"] or 1, []).append(line)
        return out or {1: []}


# --------------------------------------------------------------------------- разбор

def decode(data: bytes) -> tuple[str, str, bool]:
    """Текст .txt из байтов: (текст, кодировка, был ли BOM). BOM UTF-8 → UTF-8 → cp1251."""
    if data.startswith(_BOM):
        return data[len(_BOM):].decode("utf-8"), "utf-8", True
    for enc in ("utf-8", "cp1251"):
        try:
            return data.decode(enc), enc, False
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1"), "latin-1", False


def _split(text: str) -> list[tuple[str, str]]:
    out = []
    for m in _LINE_RE.finditer(text):
        chunk = m.group(0)
        e = _EOL_RE.search(chunk)
        eol = e.group(1) if e else ""
        out.append((chunk[: len(chunk) - len(eol)], eol))
    return out


def _detect_newline(lines: list[tuple[str, str]]) -> str:
    for _, eol in lines:
        if eol:
            return eol
    return "\n"


def _parse_body_line(content: str, eol: str, player: int | None):
    m = _NOTE_RE.match(content)
    if m:
        return Note(type=m.group(1), start=int(m.group(2)), length=int(m.group(3)),
                    pitch=int(m.group(4)), text=m.group(5) or "", player=player,
                    eol=eol, raw=content)
    m = _BREAK_RE.match(content)
    if m:
        return LineBreak(beat=int(m.group(1)),
                         beat2=int(m.group(2)) if m.group(2) is not None else None,
                         eol=eol, raw=content)
    m = _PLAYER_RE.match(content)
    if m:
        return PlayerMark(player=int(m.group(1)), eol=eol, raw=content)
    if _END_RE.match(content):
        return End(eol=eol, raw=content)
    return RawLine(content=content, eol=eol, raw=content)


def parse(data: bytes) -> Song:
    """Разобрать .txt (байты) в модель :class:`Song`."""
    text, encoding, bom = decode(data)
    lines = _split(text)
    song = Song(encoding=encoding, bom=bom, newline=_detect_newline(lines))
    in_headers = True
    player: int | None = None
    ended = False
    for content, eol in lines:
        if in_headers:
            m = _HEADER_RE.match(content)
            if m:
                h = Header(key=m.group(1), value=m.group(2), eol=eol, raw=content)
                h._freeze()
                song.headers.append(h)
                continue
            if not content.strip():
                r = RawLine(content=content, eol=eol, raw=content)
                r._freeze()
                song.headers.append(r)
                continue
            in_headers = False
        if ended:
            item = RawLine(content=content, eol=eol, raw=content)
        else:
            item = _parse_body_line(content, eol, player)
            if isinstance(item, PlayerMark):
                player = item.player
            elif isinstance(item, End):
                ended = True
        item._freeze()
        song.body.append(item)
    return song


def render(song: Song) -> bytes:
    """Записать модель в байты (кодировка, BOM и переводы строк — как у модели)."""
    text = "".join(line.line() + line.eol for line in [*song.headers, *song.body])
    data = text.encode(song.encoding)
    return (_BOM + data) if song.bom else data


# --------------------------------------------------------------------------- правки

def _insert_index(keys: list[str | None], key: str) -> int:
    """Позиция вставки нового заголовка ``key`` в список заголовков ``keys``."""
    for neighbour in _INSERT_AFTER.get(key, ()):
        for i in range(len(keys) - 1, -1, -1):
            if keys[i] == neighbour:
                return i + 1
    # По умолчанию — после последнего настоящего заголовка.
    for i in range(len(keys) - 1, -1, -1):
        if keys[i] is not None:
            return i + 1
    return 0


def set_header_line(data: bytes, key: str, value: str) -> bytes:
    """Вставить или заменить строку ``#KEY:value``, не трогая остальные байты.

    Работает на уровне строк (без пересборки модели): кодировка, BOM и переводы
    строк сохраняются. Если значение нельзя записать в кодировке файла —
    ``ValueError``.
    """
    text, encoding, bom = decode(data)
    lines = _split(text)
    newline = _detect_newline(lines)
    key_u = key.upper()
    header_end = 0
    keys: list[str | None] = []
    for content, _ in lines:
        m = _HEADER_RE.match(content)
        if m:
            keys.append(m.group(1).strip().upper())
        elif not content.strip():
            keys.append(None)
        else:
            break
        header_end += 1

    for i in range(header_end):
        if keys[i] == key_u:
            content, eol = lines[i]
            m = _HEADER_RE.match(content)
            lines[i] = (f"#{m.group(1)}:{value}", eol)
            break
    else:
        idx = _insert_index(keys, key_u)
        if idx > 0 and lines[idx - 1][1] == "":
            lines[idx - 1] = (lines[idx - 1][0], newline)
        lines.insert(idx, (f"#{key_u}:{value}", newline))

    out = "".join(c + e for c, e in lines)
    try:
        encoded = out.encode(encoding)
    except UnicodeEncodeError as exc:
        raise ValueError(
            f"Значение заголовка #{key_u} нельзя записать в кодировке файла ({encoding})"
        ) from exc
    return (_BOM + encoded) if bom else encoded


def fix_zero_length(song: Song) -> int:
    """Ноты длины 0 → 1; перекрытия убираются сдвигом последующих нот строки
    вправо, разрыв строки ставится не раньше конца последней ноты.

    Возвращает число исправленных нот (0 — модель не менялась).
    """
    fixed = 0
    for n in song.notes():
        if n.length == 0:
            n.length = 1
            fixed += 1
    if not fixed:
        return 0

    relative = song.relative
    body = song.body
    prev_end: int | None = None
    for i, item in enumerate(body):
        if isinstance(item, PlayerMark):
            prev_end = None
        elif isinstance(item, Note):
            if prev_end is not None and item.start < prev_end:
                delta = prev_end - item.start
                for later in body[i:]:
                    if isinstance(later, Note):
                        later.start += delta
                    elif isinstance(later, (LineBreak, PlayerMark, End)):
                        break
            prev_end = item.end
        elif isinstance(item, LineBreak):
            if prev_end is not None and item.beat < prev_end:
                item.beat = prev_end
            if item.beat2 is not None and item.beat2 < item.beat:
                item.beat2 = item.beat
            if relative and prev_end is not None:
                shift = item.beat2 if item.beat2 is not None else item.beat
                prev_end = prev_end - shift
        elif isinstance(item, End):
            break
    return fixed


def number(value: str | None, default: float | None) -> float | None:
    """Число заголовка (#BPM, #GAP; запятая как точка). Пусто — default; мусор — ValueError."""
    if value is None or not value.strip():
        return default
    return float(value.strip().replace(",", "."))


def beat_to_ms(song: Song, beat: float) -> float:
    """Время бита в миллисекундах: ``GAP + beat * 60000 / (BPM * 4)``."""
    bpm = number(song.header("BPM"), 0.0)
    if bpm <= 0:
        raise ValueError("В файле нет корректного #BPM")
    gap = number(song.header("GAP"), 0.0)
    return gap + beat * 60000.0 / (bpm * 4)


def singer_names(song: Song) -> tuple[str, str]:
    """Имена певцов дуэта: ``#P1/#P2``, иначе ``#DUETSINGERP1/2``; нет — пустая строка."""
    names = []
    for i in (1, 2):
        value = song.header(f"P{i}")
        if value is None:
            value = song.header(f"DUETSINGERP{i}")
        names.append((value or "").strip())
    return names[0], names[1]


def set_singer_names(song: Song, p1: str, p2: str) -> None:
    """Записать имена певцов: ``#P1/#P2``; ``#DUETSINGERP*`` — только если уже были.

    Пустое имя удаляет оба заголовка этого певца.
    """
    for i, name in ((1, p1), (2, p2)):
        name = (name or "").strip()
        if not name:
            song.remove_header(f"P{i}")
            song.remove_header(f"DUETSINGERP{i}")
            continue
        song.set_header(f"P{i}", name)
        if song.header(f"DUETSINGERP{i}") is not None:
            song.set_header(f"DUETSINGERP{i}", name)


def set_line_starts(song: Song, starts) -> None:
    """Границы строк соло: перед нотой с индексом из ``starts`` (кроме 0) — разрыв, прочие убраны.

    Разрыв, уже стоящий перед такой нотой, остаётся как был (байт в байт); новый пишется
    ``- <конец предыдущей ноты>``. Разрывы до первой и после последней ноты не трогаются.
    Дуэт, ``#RELATIVE`` или индекс вне нот — ``ValueError``.
    """
    if song.is_duet:
        raise ValueError("Границы строк по тексту меняются только у соло, не у дуэта")
    if song.relative:
        raise ValueError("Границы строк не меняются в песне с #RELATIVE")
    count = len(song.notes())
    wanted = set()
    for s in starts:
        s = int(s)
        if s < 0 or s >= count:
            raise ValueError(f"Начало строки {s} вне нот песни (нот {count})")
        if s:
            wanted.add(s)
    body: list = []
    index = 0  # индекс очередной ноты
    pending: list = []  # разрывы и прочие строки после предыдущей ноты
    prev: Note | None = None
    ended = False
    for item in song.body:
        if ended or isinstance(item, End):
            ended = True
            body.extend(pending)
            pending = []
            body.append(item)
        elif isinstance(item, Note):
            if prev is not None:
                has_break = any(isinstance(x, LineBreak) for x in pending)
                if index in wanted:
                    body.extend(pending)
                    if not has_break:
                        body.append(LineBreak(beat=prev.end, eol=song.newline))
                else:
                    body.extend(x for x in pending if not isinstance(x, LineBreak))
            else:
                body.extend(pending)
            pending = []
            body.append(item)
            prev = item
            index += 1
        elif prev is None:
            body.append(item)
        else:
            pending.append(item)
    body.extend(pending)
    song.body = body


def extract_lyrics(song: Song) -> str:
    """Текст песни из нот: строка на строку, партии дуэта через пустую строку."""
    blocks: list[list[str]] = []
    current_player: object = object()
    for line in song.lines():
        if line["player"] != current_player:
            blocks.append([])
            current_player = line["player"]
        words = "".join(n.text for n in line["notes"]).replace("~", "")
        words = re.sub(r"\s+", " ", words).strip()
        if words:
            blocks[-1].append(words)
    return "\n\n".join("\n".join(b) for b in blocks if b)
