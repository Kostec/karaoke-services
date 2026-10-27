"""Свои теги пользователя: Tags поверх SQLite."""

import pytest

from karaoke_core import db


@pytest.fixture
def tags(tmp_path):
    return db.Tags(db.connect(tmp_path / "karaoke.sqlite"))


def test_palette_and_defaults():
    assert db.TAG_COLORS == ("blue", "violet", "pink", "orange", "yellow", "teal", "gray", "red")
    assert db.DEFAULT_TAG_COLOR == "blue"
    assert db.TAG_NAME_MAX == 40


def test_create_default_color_and_list_sorted_by_name(tags):
    b = tags.create("  баллады  ")
    a = tags.create("Апрель", "pink")
    assert (b.name, b.color) == ("баллады", "blue")
    assert b.to_dict() == {"id": b.id, "name": "баллады", "color": "blue"}
    assert [t.name for t in tags.list()] == ["Апрель", "баллады"]
    assert tags.get(a.id).color == "pink"
    assert tags.get("nope") is None


@pytest.mark.parametrize("name, text", [
    ("", "Введите название тега"),
    ("   ", "Введите название тега"),
    ("я" * 41, "Не длиннее 40 символов"),
])
def test_create_bad_name(tags, name, text):
    with pytest.raises(db.TagError) as e:
        tags.create(name)
    assert (str(e.value), e.value.field) == (text, "name")


def test_name_of_40_chars_is_fine(tags):
    assert tags.create("я" * 40).name == "я" * 40


def test_duplicate_ignores_case_yo_and_spaces(tags):
    tags.create("Ёлки  Палки")
    for name in ("ёлки палки", " ЕЛКИ ПАЛКИ ", "елки   палки"):
        with pytest.raises(db.TagError) as e:
            tags.create(name)
        assert (str(e.value), e.value.field) == ("Такой тег уже есть", "name")


def test_unknown_color(tags):
    with pytest.raises(db.TagError) as e:
        tags.create("x", "green")
    assert (str(e.value), e.value.field) == ("Неизвестный цвет", "color")


def test_update_rename_recolor_and_duplicate(tags):
    a = tags.create("рок")
    b = tags.create("поп")
    assert tags.update(a.id, name="Рок").name == "Рок"  # тот же тег — не дубль
    t = tags.update(a.id, color="red")
    assert (t.name, t.color) == ("Рок", "red")
    with pytest.raises(db.TagError) as e:
        tags.update(b.id, name="РОК")
    assert e.value.field == "name"
    with pytest.raises(db.TagError):
        tags.update(b.id, color="lime")
    with pytest.raises(db.TagError):
        tags.update(b.id, name=" ")
    with pytest.raises(KeyError):
        tags.update("nope", name="x")


def test_song_links_counts_and_delete(tags):
    a = tags.create("б-тег")
    b = tags.create("а-тег")
    assert tags.set_for_song("k1", [a.id, b.id]) == [b.id, a.id]  # по имени
    assert tags.set_for_song("k2", [a.id]) == [a.id]
    assert tags.for_songs(["k1", "k2", "k3"]) == {"k1": [b.id, a.id], "k2": [a.id]}
    assert tags.for_songs([]) == {}
    assert tags.counts() == {a.id: 2, b.id: 1}
    assert tags.set_for_song("k1", [b.id]) == [b.id]  # заменяет набор
    assert tags.for_songs(["k1"]) == {"k1": [b.id]}
    with pytest.raises(KeyError):
        tags.set_for_song("k1", [b.id, "nope"])
    assert tags.for_songs(["k1"]) == {"k1": [b.id]}  # неудача ничего не меняет
    assert tags.delete(a.id) == 1
    assert tags.get(a.id) is None and tags.for_songs(["k2"]) == {}
    with pytest.raises(KeyError):
        tags.delete(a.id)
    assert tags.set_for_song("k1", []) == []
    assert tags.counts() == {}


def test_for_songs_many_keys(tags):
    t = tags.create("x")
    keys = [f"k{i}" for i in range(1500)]
    for k in keys[::100]:
        tags.set_for_song(k, [t.id])
    got = tags.for_songs(keys)
    assert sorted(got) == sorted(keys[::100])


def test_copy_key_without_duplicates_and_drop_key(tags):
    from karaoke_core import naming

    a, b = tags.create("Апрель"), tags.create("Баллады")
    old, new = naming.song_tag_key("Кино", "Звезда"), naming.song_tag_key("Кино", "Звезда по имени Солнце")
    tags.set_for_song(old, [a.id, b.id])
    tags.set_for_song(new, [a.id])  # у нового ключа уже есть тег — дубля не будет
    assert tags.copy_key(old, new) == 1
    assert tags.for_songs([old, new]) == {old: [a.id, b.id], new: [a.id, b.id]}
    assert tags.copy_key(old, new) == 0  # повтор (задание другой копии) ничего не меняет
    assert tags.copy_key(new, new) == 0
    assert tags.drop_key(old) == 2
    assert tags.drop_key(old) == 0
    assert tags.for_songs([old, new]) == {new: [a.id, b.id]}
    assert tags.counts() == {a.id: 1, b.id: 1}


def test_create_none_or_empty_color_is_unknown(tags):
    for color in (None, ""):
        with pytest.raises(db.TagError) as e:
            tags.create("x", color)
        assert (str(e.value), e.value.field) == ("Неизвестный цвет", "color")
    assert tags.list() == []


def test_unique_violation_becomes_tag_error(tags, monkeypatch):
    """Гонка: проверка дубля прошла у обоих, второй INSERT/UPDATE упирается в UNIQUE(name_key)."""
    import sqlite3

    a = tags.create("Рок")
    b = tags.create("Поп")
    monkeypatch.setattr(db.Tags, "_check_unique", lambda self, key, except_id=None: None)
    for call in (lambda: tags.create("рок"), lambda: tags.update(b.id, name="РОК")):
        try:
            call()
        except sqlite3.IntegrityError as e:  # pragma: no cover - это и есть баг
            pytest.fail(f"IntegrityError наружу: {e}")
        except db.TagError as e:
            assert (str(e), e.field) == ("Такой тег уже есть", "name")
        else:
            pytest.fail("дубль создан")
    assert [t.name for t in tags.list()] == ["Поп", "Рок"] and tags.get(a.id).name == "Рок"


def test_parallel_create_on_two_connections(tmp_path):
    import threading

    path = tmp_path / "karaoke.sqlite"
    db.connect(path)
    for round_ in range(5):
        name = f"тег {round_}"
        barrier = threading.Barrier(2)
        results: list = []

        def work():
            t = db.Tags(db.connect(path))
            barrier.wait()
            try:
                results.append(t.create(name))
            except Exception as e:  # noqa: BLE001 - собираем всё, что вылетело
                results.append(e)

        threads = [threading.Thread(target=work) for _ in range(2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        ok = [r for r in results if isinstance(r, db.Tag)]
        errors = [r for r in results if not isinstance(r, db.Tag)]
        assert len(ok) == 1 and len(errors) == 1, results
        assert isinstance(errors[0], db.TagError) and (str(errors[0]), errors[0].field) == (
            "Такой тег уже есть", "name")


def test_change_for_songs_adds_and_removes_without_replacing(tags):
    a, b, c = tags.create("А"), tags.create("Б"), tags.create("В")
    tags.set_for_song("k1", [a.id])
    tags.set_for_song("k2", [a.id, b.id])
    # k1: +b; k2: b уже есть, снимаем a; k3: новая песня
    assert tags.change_for_songs(["k1", "k2", "k3"], add=[b.id], remove=[a.id]) == 3
    assert tags.for_songs(["k1", "k2", "k3"]) == {"k1": [b.id], "k2": [b.id], "k3": [b.id]}
    # повтор ничего не меняет
    assert tags.change_for_songs(["k1", "k2", "k3"], add=[b.id], remove=[a.id]) == 0
    assert tags.change_for_songs(["k1"], add=[c.id], remove=[]) == 1
    assert tags.for_songs(["k1"]) == {"k1": [b.id, c.id]}
    assert tags.change_for_songs([], add=[a.id], remove=[]) == 0


def test_change_for_songs_same_tag_in_add_and_remove_is_added(tags):
    a, b = tags.create("А"), tags.create("Б")
    tags.set_for_song("k1", [a.id])
    # «А» и в add, и в remove — побеждает add: тег у песни остаётся, у новой — появляется
    assert tags.change_for_songs(["k1", "k2"], add=[a.id, b.id], remove=[a.id]) == 2
    assert tags.for_songs(["k1", "k2"]) == {"k1": [a.id, b.id], "k2": [a.id, b.id]}


def test_change_for_songs_unknown_id_changes_nothing(tags):
    a = tags.create("А")
    tags.set_for_song("k1", [a.id])
    for add, remove in (([a.id, "nope"], []), ([], ["nope"])):
        with pytest.raises(KeyError):
            tags.change_for_songs(["k1", "k2"], add=add, remove=remove)
    assert tags.for_songs(["k1", "k2"]) == {"k1": [a.id]}
