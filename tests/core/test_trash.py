"""Корзина в томе: перенос, версии, список, восстановление, очистка.

Шов — публичный API ``karaoke_core.trash`` поверх ``LocalStorage`` во временной папке.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from karaoke_core.storage import LocalStorage
from karaoke_core.trash import Trash, TrashError

TXT = ("#TITLE:Песня\n#ARTIST:Исполнитель\n#MP3:Исполнитель - Песня.mp3\n#BPM:300\n"
       ": 0 4 1 Ля\nE\n").encode("utf-8")
REL = "Исполнитель/Исполнитель - Песня"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    out = tmp_path / "out"
    song = out / REL
    song.mkdir(parents=True)
    (song / "Исполнитель - Песня.txt").write_bytes(TXT)
    (song / "Исполнитель - Песня.mp3").write_bytes(b"m" * 5000)
    clock = Clock(T0)
    return LocalStorage(str(out)), Trash(tmp_path / "trash", clock=clock), out, clock


def test_move_to_trash_copies_then_deletes_and_lists(env, tmp_path):
    st, trash, out, _ = env
    item = trash.move_to_trash(st, REL, "удалено пользователем")
    assert not (out / REL).exists()
    entry = Path(item.path)
    assert entry.parent == tmp_path / "trash"
    assert entry.name.startswith("20261001T120000Z__")
    assert (entry / REL / "Исполнитель - Песня.mp3").stat().st_size == 5000
    meta = json.loads((entry / "meta.json").read_text("utf-8"))
    assert meta["rel_dir"] == REL and meta["reason"] == "удалено пользователем"
    [listed] = trash.list()
    assert (listed.id, listed.artist, listed.title) == (item.id, "Исполнитель", "Песня")
    assert listed.target_id == st.target_id
    assert listed.days_left(30, now=T0 + timedelta(days=10)) == 20


def test_move_to_trash_keeps_original_when_copy_size_differs(env, tmp_path):
    st, trash, out, _ = env

    class Truncating(LocalStorage):
        def download_dir(self, rel_dir, local):
            got = super().download_dir(rel_dir, local)
            for p in got:
                if p.suffix == ".mp3":
                    p.write_bytes(b"m" * 10)
            return got

    with pytest.raises(TrashError):
        trash.move_to_trash(Truncating(str(out)), REL, "x")
    assert (out / REL / "Исполнитель - Песня.mp3").stat().st_size == 5000
    assert trash.list() == []
    assert not any((tmp_path / "trash").iterdir())


def test_move_missing_song_is_clear_error(env):
    st, trash, _, _ = env
    with pytest.raises(TrashError) as e:
        trash.move_to_trash(st, "Нет/Нет - Такой", "x")
    assert "не найдена" in str(e.value)


def test_restore_returns_folder_and_removes_entry(env):
    st, trash, out, _ = env
    item = trash.move_to_trash(st, REL, "x")
    trash.restore(st, item.id)
    assert (out / REL / "Исполнитель - Песня.txt").read_bytes() == TXT
    assert (out / REL / "Исполнитель - Песня.mp3").stat().st_size == 5000
    assert trash.list() == []
    assert not Path(item.path).exists()


def test_restore_into_occupied_place_fails_and_keeps_entry(env):
    st, trash, out, _ = env
    item = trash.move_to_trash(st, REL, "x")
    (out / REL).mkdir(parents=True)
    (out / REL / "new.txt").write_bytes(b"new")
    with pytest.raises(TrashError) as e:
        trash.restore(st, item.id)
    assert str(e.value) == "Сначала удалите или переименуйте существующую"
    assert [i.id for i in trash.list()] == [item.id]
    assert (out / REL / "new.txt").read_bytes() == b"new"


def test_restore_unknown_id(env):
    st, trash, _, _ = env
    with pytest.raises(TrashError):
        trash.restore(st, "nope")


def test_save_version_keeps_original_and_restores_over_current(env):
    st, trash, out, clock = env
    rel_file = f"{REL}/Исполнитель - Песня.txt"
    v = trash.save_version(st, rel_file)
    assert (out / rel_file).read_bytes() == TXT
    assert v.kind == "version" and v.rel_file == rel_file
    st.write_atomic(rel_file, b"edited")
    clock.t = T0 + timedelta(minutes=5)
    trash.restore(st, v.id)
    assert (out / rel_file).read_bytes() == TXT
    # отменённая правка не потерялась — она теперь сама версия в корзине
    [newer] = trash.list()
    assert newer.kind == "version" and newer.id != v.id
    assert (Path(newer.path) / rel_file).read_bytes() == b"edited"


def test_purge_removes_only_older_than_n_days(env, tmp_path):
    st, trash, out, clock = env
    old = trash.move_to_trash(st, REL, "старое")
    clock.t = T0 + timedelta(days=5)
    (out / REL).mkdir(parents=True)
    (out / REL / "Исполнитель - Песня.txt").write_bytes(TXT)
    fresh = trash.move_to_trash(st, REL, "новое")
    assert trash.purge(30, now=T0 + timedelta(days=30, hours=-1)) == 0
    assert trash.purge(30, now=T0 + timedelta(days=31)) == 1
    assert [i.id for i in trash.list()] == [fresh.id]
    assert not Path(old.path).exists()
    assert trash.purge(30, now=T0 + timedelta(days=36)) == 1
    assert trash.list() == []


def test_list_is_newest_first(env):
    st, trash, out, clock = env
    a = trash.save_version(st, f"{REL}/Исполнитель - Песня.txt")
    clock.t = T0 + timedelta(hours=1)
    b = trash.save_version(st, f"{REL}/Исполнитель - Песня.mp3")
    assert [i.id for i in trash.list()] == [b.id, a.id]


def test_restore_into_other_target_is_refused(env, tmp_path):
    st, trash, out, _ = env
    item = trash.move_to_trash(st, REL, "x")
    other = LocalStorage(str(tmp_path / "other"))
    with pytest.raises(TrashError) as e:
        trash.restore(other, item.id)
    assert str(e.value).startswith(f"Песня была удалена из другой папки результата: {st.label}")
    assert not (tmp_path / "other" / REL).exists()
    assert [i.id for i in trash.list()] == [item.id]


def test_save_version_checks_copy_against_file_size_only(env):
    st, trash, out, _ = env
    rel_file = f"{REL}/Исполнитель - Песня.mp3"

    class ShortRead(LocalStorage):
        def open_read(self, rel):
            import io
            return io.BytesIO(super().read(rel)[:10])

        def sizes(self, rel_dir):
            raise AssertionError("обход всей папки не нужен")

    with pytest.raises(TrashError):
        trash.save_version(ShortRead(str(out)), rel_file)
    assert trash.list() == []
    v = trash.save_version(type("NoWalk", (LocalStorage,), {"sizes": ShortRead.sizes})(str(out)),
                           rel_file)
    assert v.files == {"Исполнитель - Песня.mp3": 5000}


def test_move_last_song_of_artist_removes_artist_dir(env):
    st, trash, out, _ = env
    trash.move_to_trash(st, REL, "x")
    assert not (out / "Исполнитель").exists()
    assert out.is_dir()


def test_trash_item_for_folder_without_song_txt(env):
    st, trash, out, _ = env
    (out / "Б/Б - В").mkdir(parents=True)
    (out / "Б/Б - В/Б - В.mp3").write_bytes(b"1")
    item = trash.move_to_trash(st, "Б/Б - В", "x")
    assert (item.artist, item.title, item.name) == ("", "", "Б - В")
