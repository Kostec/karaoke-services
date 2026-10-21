"""Шов 3: импорт дуэта (история 1) — партии P1/P2 и имена певцов доезжают до папки результата."""

from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"
DUET = (Path(__file__).resolve().parents[1] / "core" / "fixtures" / "duet.txt").read_bytes()
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 64
GPU_OFF = {"ok": False, "name": None, "vram_mb": None, "error": "нет GPU (тест)"}
REL_DIR, BASE = "Он и Она/Он и Она - Дуэт", "Он и Она - Дуэт"


def _enqueue(world):
    params = {"source": "usdb", "usdb_id": 1, "youtube_url": None, "instrumental": False,
              "rel_dir": REL_DIR, "replace": False, "replace_rel_dir": None,
              "target_id": world.storage.target_id}

    def make(job_id: int) -> dict:
        d = world.paths.job_in(REL_DIR, job_id)
        d.mkdir(parents=True)
        (d / "song.txt").write_bytes(DUET)
        (d / "input.mp3").write_bytes(MP3)
        return {**params, "inputs": {"dir": world.paths.rel(d), "txt": world.paths.rel(d / "song.txt"),
                                     "audio": world.paths.rel(d / "input.mp3")}}

    return world.jobs.enqueue_with("import", {"artist": "Он и Она", "title": "Дуэт"}, make)


def test_import_duet_keeps_players_and_singer_names(world):
    job = _enqueue(world)
    world.run(gpu=GPU_OFF)

    done = world.jobs.get(job.id)
    assert (done.state, done.error) == ("done", None)
    lines = (world.out / REL_DIR / f"{BASE}.txt").read_bytes().decode("utf-8").splitlines()
    assert {"#P1:Он", "#P2:Она"} <= set(lines)
    # тело то же, кроме уже существующей правки нот длины 0 (fix_zero_length)
    assert [ln for ln in lines if not ln.startswith("#")] == [
        "P1", ": 0 4 1 При", ": 4 4 2 вет ", "- 10", ": 12 4 1 Как ",
        "P2", ": 0 4 6 Здрав", ": 4 4 7 ствуй ", "- 10", ": 12 4 8 Хо", ": 16 4 8 ро", ": 20 1 8 шо",
        "E"]
