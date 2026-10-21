"""Границы строк песни по исходному тексту пользователя.

UltraSinger без таймингов LRC режет строки по паузам в голосе, а не по строкам текста
(«Что / б тамбур прокуренным / был»). Здесь слова нот сопоставляются по порядку со словами
текста, и начало каждой строки текста ставится на первую ноту её первого найденного слова.
Чистая логика: модуль ничего не читает и не пишет (кроме модели песни в :func:`align_song`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from . import ultrastar

__all__ = ["LineAlign", "align_line_starts", "align_song", "line_starts", "norm_word"]

_NON_WORD = re.compile(r"[\W_]+")
# Похожесть слов (доля общих букв), при которой несовпавшие слова одной длины участка
# всё же считаются одним словом: опечатка, «прокуреным» ↔ «прокуренным».
_FUZZY = 0.75


@dataclass(frozen=True)
class LineAlign:
    starts: list[int]  # индексы нот — начала строк, по возрастанию, первый 0
    unmatched: int  # строк текста, ни одно слово которых не нашлось в нотах
    total: int  # строк текста, в которых есть слова


@dataclass
class _Word:
    norm: str
    first: int  # индекс первой ноты слова
    last: int  # индекс последней ноты слова


def norm_word(text: str) -> str:
    """Слово для сравнения: без регистра, ё=е, без пунктуации, скобок и «~»."""
    return _NON_WORD.sub("", text.lower().replace("ё", "е"))


def _is_free(text: str) -> bool:
    """Свободная нота: пустая или «~» (с любыми пробелами) — тянет предыдущую гласную."""
    return text.strip() in ("", "~")


def _note_words(note_texts: list[str]) -> list[_Word]:
    """Слова нот по правилам UltraSinger (как ``wordStart`` в notes-model.js).

    Нота с текстом начинает слово, если её слог начинается с пробела или пробелом кончается
    предыдущий слог (через свободные ноты — до последнего слога с текстом); свободная нота
    продолжает текущее слово. Слова без букв (только пунктуация) в сопоставлении не участвуют.
    """
    words: list[tuple[list[str], int, int]] = []
    boundary = True  # следующая нота с текстом начинает слово
    for i, raw in enumerate(note_texts):
        text = str(raw or "")
        if _is_free(text):
            if words:
                parts, first, _ = words[-1]
                words[-1] = (parts, first, i)
            else:
                words.append(([], i, i))
        else:
            if boundary or not words or text[:1].isspace():
                words.append(([text], i, i))
            else:
                parts, first, _ = words[-1]
                parts.append(text)
                words[-1] = (parts, first, i)
        if text[-1:].isspace():
            boundary = True
        elif not _is_free(text):
            boundary = False
    out = []
    for parts, first, last in words:
        norm = norm_word("".join(parts))
        if norm:
            out.append(_Word(norm, first, last))
    return out


def _lyric_lines(lyrics: str) -> list[list[str]]:
    """Строки текста словами; строки без слов (пустые, только пунктуация) пропускаются."""
    lines = []
    for line in str(lyrics or "").splitlines():
        words = [w for w in (norm_word(t) for t in line.split()) if w]
        if words:
            lines.append(words)
    return lines


def _match(a: list[str], b: list[str]) -> dict[int, int]:
    """Сопоставление слов текста ``a`` словам нот ``b`` по порядку: индекс в a → индекс в b."""
    pairs: dict[int, int] = {}
    ops = SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            pairs.update({i1 + k: j1 + k for k in range(i2 - i1)})
        elif tag == "replace" and i2 - i1 == j2 - j1:
            for k in range(i2 - i1):
                if SequenceMatcher(None, a[i1 + k], b[j1 + k]).ratio() >= _FUZZY:
                    pairs[i1 + k] = j1 + k
    return pairs


def align_line_starts(note_texts: list[str], lyrics: str,
                      existing_starts: Iterable[int] = ()) -> LineAlign:
    """Начала строк (индексы нот) по строкам исходного текста.

    Начало строки текста — первая нота её первого сопоставленного слова. Несопоставленные слова
    нот между соседними строками текста достаются строке, у которой не хватает слов (в конце
    предыдущей или в начале следующей). Там, где между найденными строками есть ненайденные
    строки текста (и до первой/после последней найденной, если текст там не кончается),
    остаются прежние границы ``existing_starts``.
    """
    n = len(note_texts)
    lines = _lyric_lines(lyrics)
    total = len(lines)
    existing = sorted({int(s) for s in existing_starts if 0 < int(s) < n})
    words = _note_words(list(note_texts))
    flat = [w for line in lines for w in line]
    line_of = [li for li, line in enumerate(lines) for _ in line]
    pairs = _match(flat, [w.norm for w in words])

    # найденные строки: (номер строки, первое/последнее найденное слово нот, слов текста до/после)
    found: list[dict] = []
    pos = 0
    for li, line in enumerate(lines):
        idx = [k for k in range(pos, pos + len(line)) if k in pairs]
        if idx:
            found.append({"li": li, "j1": pairs[idx[0]], "j2": pairs[idx[-1]],
                          "lead": idx[0] - pos, "trail": pos + len(line) - 1 - idx[-1]})
        pos += len(line)
    unmatched = total - len(found)
    if not found or n == 0:
        return LineAlign(starts=[0, *existing], unmatched=unmatched, total=total)

    starts = {0}
    first = found[0]
    if first["li"] > 0:
        starts.add(words[first["j1"]].first)
        starts.update(s for s in existing if s < words[first["j1"]].first)
    for prev, cur in zip(found, found[1:]):
        if cur["li"] == prev["li"] + 1:
            gap = cur["j1"] - prev["j2"] - 1  # слов нот между строками без пары
            take = gap if cur["lead"] == 0 else min(prev["trail"], gap)
            j = prev["j2"] + 1 + take if take < gap else cur["j1"]
            starts.add(words[j].first)
        else:
            lo, hi = words[prev["j2"]].last, words[cur["j1"]].first
            starts.add(hi)
            starts.update(s for s in existing if lo < s < hi)
    last = found[-1]
    if last["li"] < total - 1:
        lo = words[last["j2"]].last
        starts.update(s for s in existing if s > lo)
    return LineAlign(starts=sorted(starts), unmatched=unmatched, total=total)


def line_starts(song: ultrastar.Song) -> list[int]:
    """Текущие начала строк соло: индексы первых нот строк."""
    out, i = [], 0
    for line in song.lines():
        if line["notes"]:
            out.append(i)
            i += len(line["notes"])
    return out


def align_song(song: ultrastar.Song, lyrics: str) -> LineAlign:
    """Выровнять строки соло ``song`` по тексту (модель меняется на месте).

    Если ни одна строка текста не нашлась, модель не трогается. Дуэт — ``ValueError``.
    """
    if song.is_duet:
        raise ValueError("Границы строк по тексту меняются только у соло, не у дуэта")
    notes = song.notes()
    result = align_line_starts([n.text for n in notes], lyrics, line_starts(song))
    if result.total and result.unmatched < result.total:
        ultrastar.set_line_starts(song, result.starts)
    return result
