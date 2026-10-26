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
