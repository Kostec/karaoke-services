"""selfcheck: правки karaoke-local в UltraSinger на месте (история 56).

UltraSinger подменяется фейковым деревом src/ во временной папке: torch и сам UltraSinger
для этих тестов не нужны. Настоящая ветка проверяется в образе worker
(`docker --context desktop-linux compose run --rm worker selfcheck`).
"""

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from karaoke_worker import selfcheck  # noqa: E402

ARG_OPTIONS_OK = '''
def arg_options():
    short = "hi:o:amv:"
    long = ["ifile=", "ofile=", "language=", "lyrics=", "vad_onset=", "vad_offset=", "midi"]
    return long, short
'''

LYRICS_ALIGNMENT_OK = '''
def find_lyrics_file(input_file_path, explicit_path=None):
    return explicit_path

def read_lyrics(path):
    return []
'''

MIDI_SEGMENT = '''
from dataclasses import dataclass

@dataclass
class MidiSegment:
    note: str
    start: float
    end: float
    word: str
'''

MIDI_CREATOR_FIXED = '''
import os
from types import SimpleNamespace

def create_midi_instrument(midi_segments):
    notes = []
    for seg in midi_segments:
        if seg.end <= seg.start:
            continue
        notes.append(SimpleNamespace(start=seg.start, end=seg.end))
    return SimpleNamespace(notes=notes)

def create_midi_file(real_bpm, song_output, midi_segments, basename_without_ext):
    create_midi_instrument(midi_segments)
    with open(os.path.join(song_output, basename_without_ext + ".mid"), "wb") as f:
        f.write(b"MThd")
'''

# Как было до правки в upstream: нота нулевой длины попадает в инструмент.
MIDI_CREATOR_UPSTREAM = MIDI_CREATOR_FIXED.replace(
    "        if seg.end <= seg.start:\n            continue\n", "")


SWIFT_F0_LOCKED = '''
class SwiftF0:  # swift-f0 0.1.2 из uv.lock UltraSinger
    def __init__(self, fmin=46.875, fmax=2093.75, confidence_threshold=0.9):
        raise RuntimeError("selfcheck не должен загружать модель")
'''

# swift-f0 0.3.0 с PyPI: другая сигнатура, вызов из pitcher.py падает с TypeError.
SWIFT_F0_030 = '''
class SwiftF0:
    def __init__(self, threads=1, spin=False):
        pass
'''


def make_ultrasinger(tmp_path: Path, *, arg_options=ARG_OPTIONS_OK, lyrics_alignment=LYRICS_ALIGNMENT_OK,
                     midi_creator=MIDI_CREATOR_FIXED, swift_f0=SWIFT_F0_LOCKED) -> Path:
    src = tmp_path / "UltraSinger" / "src"
    files = {
        "UltraSinger.py": "import sys\n" + arg_options,
        "modules/Midi/MidiSegment.py": MIDI_SEGMENT,
        "modules/Midi/midi_creator.py": midi_creator,
        "swift_f0/__init__.py": swift_f0,  # src/ стоит первым в PYTHONPATH проверки
    }
    if lyrics_alignment is not None:
        files["modules/Speech_Recognition/lyrics_alignment.py"] = lyrics_alignment
    for rel, text in files.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    return tmp_path / "UltraSinger"


def failed(results):
    return [r for r in results if not r.ok]


def test_missing_vad_flag_is_reported_by_name(tmp_path):
    us = make_ultrasinger(tmp_path, arg_options=ARG_OPTIONS_OK.replace('"vad_offset=", ', ""))

    bad = failed(selfcheck.run_checks(us))

    assert len(bad) == 1
    assert "--vad_offset" in bad[0].message
    assert "--lyrics" not in bad[0].message


def test_intact_branch_passes_all_checks(tmp_path):
    us = make_ultrasinger(tmp_path)

    results = selfcheck.run_checks(us)

    assert failed(results) == []
    assert len(results) == 4
    assert selfcheck.main(us) == 0


def test_missing_lyrics_alignment_module_is_reported_by_name(tmp_path, capsys):
    us = make_ultrasinger(tmp_path, lyrics_alignment=None)

    bad = failed(selfcheck.run_checks(us))

    assert len(bad) == 1
    assert "lyrics_alignment" in bad[0].message
    assert selfcheck.main(us) == 1
    assert "lyrics_alignment" in capsys.readouterr().out


def test_zero_length_note_in_midi_is_reported_by_name(tmp_path):
    us = make_ultrasinger(tmp_path, midi_creator=MIDI_CREATOR_UPSTREAM)

    bad = failed(selfcheck.run_checks(us))

    assert len(bad) == 1
    assert "midi_creator" in bad[0].message
    assert "нулевой длины" in bad[0].message


def test_midi_creator_crash_on_zero_length_is_reported_by_name(tmp_path):
    crashing = MIDI_CREATOR_UPSTREAM.replace(
        "        notes.append(", "        assert seg.end > seg.start, 'end<=start'\n        notes.append(")
    us = make_ultrasinger(tmp_path, midi_creator=crashing)

    bad = failed(selfcheck.run_checks(us))

    assert len(bad) == 1
    assert "midi_creator" in bad[0].message


def test_flag_only_in_help_text_or_dead_branch_does_not_pass(tmp_path):
    # Строка «lyrics=» есть в тексте справки и в мёртвой ветке, но getopt её не получает.
    dead = '''
HELP = "  --lyrics=<file>  --vad_onset=<x>  --vad_offset=<x>   (lyrics= vad_onset= vad_offset=)"

def arg_options():
    """Справка: lyrics= vad_onset= vad_offset="""
    short = "hi:o:amv:"
    long = ["ifile=", "ofile=", "language=", "midi"]
    if False:
        long += ["lyrics=", "vad_onset=", "vad_offset="]
    return long, short
'''
    us = make_ultrasinger(tmp_path, arg_options=dead)

    bad = failed(selfcheck.run_checks(us))

    assert len(bad) == 1
    for flag in ("--lyrics", "--vad_onset", "--vad_offset"):
        assert flag in bad[0].message


def test_incompatible_swift_f0_signature_is_reported(tmp_path):
    us = make_ultrasinger(tmp_path, swift_f0=SWIFT_F0_030)

    bad = failed(selfcheck.run_checks(us))

    assert len(bad) == 1
    assert "пропала совместимость" in bad[0].message
    assert "SwiftF0" in bad[0].message and "confidence_threshold" in bad[0].message
