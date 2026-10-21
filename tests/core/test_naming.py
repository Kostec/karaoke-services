from karaoke_core import naming


def test_safe_name_replaces_forbidden_characters():
    assert naming.safe_name('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_safe_name_replaces_control_characters():
    assert naming.safe_name("a\tb\nc\x00d\x7f") == "a_b_c_d_"


def test_safe_name_strips_trailing_dots_and_spaces():
    assert naming.safe_name("T.N.T. . ") == "T.N.T"
    assert naming.safe_name("Мама  ") == "Мама"


def test_safe_name_keeps_cyrillic_and_inner_punctuation():
    assert naming.safe_name("Ёлка, ёж & Co.!") == "Ёлка, ёж & Co.!"


def test_safe_name_never_empty():
    assert naming.safe_name("...") == "_"
    assert naming.safe_name("") == "_"


def test_base_name_and_song_dir():
    assert naming.base_name("Кино", "Группа крови") == "Кино - Группа крови"
    assert naming.song_dir("Кино", "Группа крови") == "Кино/Кино - Группа крови"


def test_song_dir_sanitizes_both_levels():
    assert naming.song_dir("AC/DC", "T.N.T.") == "AC_DC/AC_DC - T.N.T"
    assert naming.song_dir(" Мумий Тролль ", "Утекай?") == "Мумий Тролль/Мумий Тролль - Утекай_"


def test_normalize_artist_ignores_case_yo_punctuation_spaces():
    assert naming.normalize_artist("Ёлка") == naming.normalize_artist("елка")
    assert naming.normalize_artist("  t.A.T.u. ") == naming.normalize_artist("tatu")
    assert naming.normalize_artist("Би-2") == naming.normalize_artist("би 2")
    assert naming.normalize_artist("Мумий  Тролль") == naming.normalize_artist("мумий тролль")


def test_normalize_artist_distinguishes_different_artists():
    assert naming.normalize_artist("Кино") != naming.normalize_artist("Kino")
    assert naming.normalize_artist("Ария") != naming.normalize_artist("Алиса")


def test_song_dir_uses_same_artist_string_on_both_levels():
    for artist in ("Bros.", "Bros. ", "AC/DC", "Ария...", " Би-2 "):
        artist_level, song_level = naming.song_dir(artist, "T").split("/")
        assert song_level.startswith(artist_level + " - "), (artist, artist_level, song_level)
    assert naming.song_dir("Bros.", "T") == "Bros/Bros - T"


def test_safe_name_replaces_all_unicode_control_characters():
    assert naming.safe_name("a\x80b\x85c\x9fd") == "a_b_c_d"


def test_song_file_names_come_from_one_place():
    assert naming.song_file("Bros.", "T", naming.SUFFIX_INSTRUMENTAL) == "Bros - T [Instrumental].mp3"
    assert naming.song_file("Bros.", "T", naming.SUFFIX_VOCALS) == "Bros - T [Vocals].mp3"
    assert naming.song_file("Bros.", "T", naming.SUFFIX_AUDIO) == "Bros - T.mp3"
    assert naming.song_file("Bros.", "T", naming.cover_suffix(".JPEG")) == "Bros - T [CO].jpg"
    assert naming.song_file("Bros.", "T", naming.cover_suffix(".png")) == "Bros - T [CO].png"


def test_video_suffix_keeps_extension_lowercased():
    assert naming.video_suffix(".MP4") == ".mp4"
    assert naming.video_suffix("mkv") == ".mkv"
    assert naming.song_file("А", "Б", naming.video_suffix(".webm")) == "А - Б.webm"


def test_video_exts_are_the_supported_containers():
    assert naming.VIDEO_EXTS == {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".mpg", ".mpeg"}


def test_video_file_name_is_file_name_with_video_extension():
    assert naming.video_file_name(" А - Б.MKV ") == "А - Б.MKV"
    assert naming.video_file_name("v=abcdefghijk,co=cover.jpg") is None  # ссылка usdb
    assert naming.video_file_name("clips/a.mp4") is None
    assert naming.video_file_name(r"clips\a.mp4") is None
    assert naming.video_file_name("a.txt") is None
    assert naming.video_file_name("") is None and naming.video_file_name(None) is None
