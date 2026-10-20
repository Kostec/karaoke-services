"""progress: маркеры лога → этап по-русски и процент (Решения §5), очистка строк (история 19)."""

from karaoke_worker.progress import LineSplitter, ProgressTracker, clean_line

H = "\x1b[92m[UltraSinger]\x1b[0m "
LOG = [
    H + "Checking GPU support.",
    H + "Separating vocals from audio with \x1b[94mdemucs\x1b[0m with model htdemucs",
    "\r 50%|#####     | 5/10",
    H + "Reduce noise from vocal audio with ffmpeg.",
    H + "Loading whisper with model large-v2 and cuda as worker",
    H + "Transcribing vocals.wav",
    "\r 80%|########  | 8/10",
    H + "Using lyrics from lyrics.txt",
    H + "Checking GPU support.",  # повтор раннего маркера не откатывает процент
    H + "Hyphenate using language code: ru",
    H + "Pitching with SwiftF0 and cuda as worker",
    H + "Creating UltraStar file out.txt",
    H + "Converting audio to mp3",
    H + "Creating midi file",
]

# Таблица §5 спецификации, переписанная вручную.
EXPECTED = [("Подготовка", 2), ("Отделение вокала", 5), ("Очистка вокала", 25), ("Загрузка модели", 30),
            ("Распознавание", 35), ("Выравнивание текста", 50), ("Расстановка слогов", 60),
            ("Определение высоты нот", 65), ("Запись песни", 80), ("Минусовка в mp3", 85), ("MIDI", 90)]


def test_stages_follow_spec_table_and_percent_never_decreases():
    t = ProgressTracker()
    updates = [u for u in (t.feed(line) for line in LOG) if u is not None]
    percents = [p for _, p in updates]
    assert percents == sorted(percents)
    stage_starts = []
    for stage, pct in updates:
        if not stage_starts or stage_starts[-1][0] != stage:
            stage_starts.append((stage, pct))
    assert stage_starts == EXPECTED
    # tqdm внутри этапа уточняет процент, но не доходит до следующего этапа
    inside = [p for s, p in updates if s == "Распознавание"]
    assert inside[0] == 35 and 35 < inside[-1] < 50
    assert t.set("Постобработка", 95) == ("Постобработка", 95)
    assert t.set("Подготовка", 2) is None


def test_clean_line_strips_ansi_and_keeps_last_tqdm_redraw():
    assert clean_line(H + "Transcribing \x1b[94mx.wav\x1b[0m\n") == "[UltraSinger] Transcribing x.wav"
    assert clean_line("\r 10%|#  |\r 60%|###|\r100%|#####|") == "100%|#####|"


def test_splitter_writes_redrawn_bar_once():
    s = LineSplitter()
    got = s.feed("start\n\r 10%|#|\r 50%|##|") + s.feed("\r100%|###|\nnext\n") + s.flush()
    assert [t for t, final in got if final] == ["start", "100%|###|", "next"]
    assert [t for t, final in got if not final] == [" 10%|#|", " 50%|##|"]


def test_marker_out_of_table_order_renames_stage_but_keeps_percent():
    t = ProgressTracker()
    t.feed(H + "Using lyrics from /x/lyrics.txt (4 lines)")
    assert t.feed(H + "Loading whisper with model large-v2") == ("Загрузка модели", 50)
