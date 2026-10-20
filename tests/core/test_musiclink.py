"""karaoke_core.musiclink: разбор ссылок, yt-dlp на фейке, Яндекс Музыка на фейковом клиенте."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from yandex_music import exceptions as ym

from karaoke_core import musiclink as ml
from karaoke_core.musiclink import LinkKind, MusicLinkError, YandexMusic, classify, ytdlp_info

FIX = Path(__file__).parent / "fixtures"
FAKE_YTDLP = [sys.executable, str(FIX / "fake_ytdlp_info.py")]


# --------------------------------------------------------------------------- classify

@pytest.mark.parametrize("url, kind, norm, ids", [
    ("https://music.yandex.ru/album/40620828/track/148124289?utm_source=web&utm_medium=copy_link",
     "yandex_track", "https://music.yandex.ru/album/40620828/track/148124289",
     {"track": "148124289", "album": "40620828"}),
    ("https://music.yandex.com/album/1/track/2/", "yandex_track",
     "https://music.yandex.com/album/1/track/2", {"track": "2", "album": "1"}),
    ("http://music.yandex.by/track/555", "yandex_track", "https://music.yandex.by/track/555", {"track": "555"}),
    ("  https://music.yandex.kz/album/777?utm_source=x  ", "yandex_album",
     "https://music.yandex.kz/album/777", {"album": "777"}),
    ("https://music.yandex.ru/users/music-blog/playlists/2712?utm_medium=copy_link", "yandex_playlist",
     "https://music.yandex.ru/users/music-blog/playlists/2712", {"user": "music-blog", "kind": "2712"}),
    ("https://music.yandex.ru/playlists/lk.2b1e1e5c-1d2a-4c1f-9b2b-0a1b2c3d4e5f?utm_source=web",
     "yandex_playlist", "https://music.yandex.ru/playlists/lk.2b1e1e5c-1d2a-4c1f-9b2b-0a1b2c3d4e5f",
     {"uuid": "lk.2b1e1e5c-1d2a-4c1f-9b2b-0a1b2c3d4e5f"}),
])
def test_classify_yandex(url, kind, norm, ids):
    link = classify(url)
    assert (link.kind, link.url, link.ids) == (kind, norm, ids)
    assert ml.is_yandex(link)


@pytest.mark.parametrize("url, norm", [
    ("https://www.youtube.com/watch?v=kXYiU_JCYtU&si=abc&utm_source=tg",
     "https://www.youtube.com/watch?v=kXYiU_JCYtU"),
    ("https://youtu.be/kXYiU_JCYtU", "https://youtu.be/kXYiU_JCYtU"),
    ("https://www.youtube.com/playlist?list=PL123", "https://www.youtube.com/playlist?list=PL123"),
    ("https://vk.com/video-12345_67890", "https://vk.com/video-12345_67890"),
    ("https://vk.ru/clip-1_2", "https://vk.ru/clip-1_2"),
    ("https://rutube.ru/video/abcdef/", "https://rutube.ru/video/abcdef/"),
    ("https://soundcloud.com/artist/song", "https://soundcloud.com/artist/song"),
    ("https://music.yandex.ru/artist/123", "https://music.yandex.ru/artist/123"),
])
def test_classify_ytdlp(url, norm):
    link = classify(url)
    assert (link.kind, link.url, link.ids) == ("ytdlp", norm, {})
    assert not ml.is_yandex(link)


@pytest.mark.parametrize("url", [
    "https://vk.com/audio-2001_456239017", "https://vk.ru/audio123_456", "https://m.vk.com/audios1234",
    "https://vk.com/music/album/-2000_1", "https://vk.com/feed?z=audio_playlist-1_2",
])
def test_classify_vk_audio_is_error(url):
    with pytest.raises(MusicLinkError, match="Аудиозаписи ВКонтакте не поддерживаются"):
        classify(url)


@pytest.mark.parametrize("url", ["", "music.yandex.ru/album/1", "ftp://x.ru/a.mp3", "javascript:alert(1)",
                                 "https://"])
def test_classify_not_http(url):
    with pytest.raises(MusicLinkError, match="Нужна ссылка вида https://"):
        classify(url)


# --------------------------------------------------------------------------- yt-dlp

def test_ytdlp_info_track():
    info = ytdlp_info("https://www.youtube.com/watch?v=kXYiU_JCYtU", FAKE_YTDLP)
    assert info.kind == "ytdlp" and info.title == "Numb"
    [t] = info.tracks
    assert t == ml.LinkTrack(url="https://www.youtube.com/watch?v=kXYiU_JCYtU", artist="Linkin Park",
                             title="Numb", duration=187.0,
                             thumbnail="https://i.ytimg.com/vi/kXYiU_JCYtU/maxresdefault.jpg")


def test_ytdlp_info_passes_flags(monkeypatch):
    seen = {}
    real_run = ml.subprocess.run

    def spy(args, **kw):
        seen["args"] = args
        return real_run(args, **kw)

    monkeypatch.setattr(ml.subprocess, "run", spy)
    ytdlp_info("https://youtu.be/x", FAKE_YTDLP)
    assert seen["args"][len(FAKE_YTDLP):] == ["-4", "-J", "--flat-playlist", "--no-warnings", "--",
                                             "https://youtu.be/x"]


def test_ytdlp_info_playlist_splits_title_and_strips_topic():
    info = ytdlp_info("https://www.youtube.com/playlist?list=PL1", FAKE_YTDLP)
    assert info.title == "Мой плейлист"
    a, b = info.tracks
    assert (a.url, a.artist, a.title, a.duration, a.thumbnail) == (
        "https://www.youtube.com/watch?v=aaa", "Кино", "Группа крови", 285.0, "https://i.ytimg.com/vi/aaa/2.jpg")
    assert (b.url, b.artist, b.title, b.duration) == (
        "https://www.youtube.com/watch?v=bbb", "Кино", "Звезда по имени Солнце", None)


def test_ytdlp_info_uploader_fallback():
    [t] = ytdlp_info("https://rutube.ru/video/1/", FAKE_YTDLP).tracks
    assert (t.artist, t.title, t.url) == ("Канал", "Песня без исполнителя", "https://rutube.ru/video/1/")


@pytest.mark.parametrize("url", ["https://youtu.be/swap", "https://youtu.be/dup"])
def test_ytdlp_info_cleans_video_title(url):
    [t] = ytdlp_info(url, FAKE_YTDLP).tracks
    assert (t.artist, t.title) == ("Linkin Park", "Numb")


def test_ytdlp_info_error_line():
    with pytest.raises(MusicLinkError) as e:
        ytdlp_info("https://example.com/error", FAKE_YTDLP)
    assert str(e.value) == ("Не удалось получить данные по ссылке: [generic] Unsupported URL: "
                            "https://example.com/error")


def test_ytdlp_info_timeout_and_bad_json_and_missing_cmd():
    with pytest.raises(MusicLinkError, match="истекло время"):
        ytdlp_info("https://example.com/sleep", FAKE_YTDLP, timeout=1)
    with pytest.raises(MusicLinkError, match="не JSON"):
        ytdlp_info("https://example.com/notjson", FAKE_YTDLP)
    with pytest.raises(MusicLinkError, match="Не удалось получить данные по ссылке"):
        ytdlp_info("https://example.com/", ["/nonexistent/yt-dlp"])


# --------------------------------------------------------------------------- Яндекс Музыка

class FakeDownload:
    def __init__(self, codec, kbps, preview=False, fail=None):
        self.codec, self.bitrate_in_kbps, self.preview, self.fail = codec, kbps, preview, fail
        self.saved_to = None

    def download(self, filename):
        if self.fail:
            raise self.fail
        self.saved_to = filename
        Path(filename).write_bytes(f"{self.codec}-{self.bitrate_in_kbps}".encode())


def make_track(tid="148124289", title="Numb", album=40620828, infos=None, available=True, version=None):
    t = NS(id=tid, title=title, version=version, available=available, duration_ms=187000,
           artists=[NS(name="Linkin Park"), NS(name="Jay-Z")], albums=[NS(id=album)],
           cover_uri="avatars.yandex.net/get-music-content/x/%%", og_image=None)
    t.get_download_info = lambda: infos if infos is not None else []
    return t


class FakeClient:
    def __init__(self, key, *, init_error=None, track=None, error=None):
        self.key, self.init_error, self.error = key, init_error, error
        self.track = track or make_track()
        self.me = NS(account=NS(uid=42))
        self.calls = []

    def init(self):
        if self.init_error:
            raise self.init_error
        return self

    def tracks(self, ids):
        self.calls.append(("tracks", ids))
        if self.error:
            raise self.error
        return [self.track]

    def albums_with_tracks(self, album_id):
        self.calls.append(("album", album_id))
        return NS(id=int(album_id), title="Meteora",
                  volumes=[[make_track("1", "Foreword", album_id)], [make_track("2", "Numb", album_id)]])

    def users_playlists(self, kind, user_id=None):
        self.calls.append(("users_playlists", kind, user_id))
        return NS(title="Плейлист", track_count=2,
                  tracks=[NS(track=make_track("5", "Раз", 9)), NS(track=None, fetch_track=lambda: make_track("6", "Два", 9))])

    def playlist(self, uuid):
        self.calls.append(("playlist", uuid))
        pl = NS(title="По uuid", track_count=1, tracks=[])
        pl.fetch_tracks = lambda: [NS(track=make_track("7", "Три", None))]
        return pl


def yandex(**kw):
    made = []

    def factory(key):
        made.append(FakeClient(key, **kw))
        return made[-1]
    return made, factory


TRACK = classify("https://music.yandex.ru/album/40620828/track/148124289?utm_source=web")


def test_yandex_info_track():
    made, factory = yandex(track=make_track(version="Live"))
    info = YandexMusic("ym-key", factory).info(TRACK)
    assert made[0].key == "ym-key" and made[0].calls == [("tracks", ["148124289:40620828"])]
    [t] = info.tracks
    assert info.kind == "yandex_track" and info.title == "Numb (Live)"
    assert t == ml.LinkTrack(url="https://music.yandex.ru/album/40620828/track/148124289",
                             artist="Linkin Park, Jay-Z", title="Numb (Live)", duration=187.0,
                             thumbnail="https://avatars.yandex.net/get-music-content/x/400x400")


def test_yandex_info_track_without_album_takes_album_from_track():
    made, factory = yandex()
    info = YandexMusic("k", factory).info(classify("https://music.yandex.ru/track/148124289"))
    assert made[0].calls == [("tracks", ["148124289"])]
    assert info.tracks[0].url == "https://music.yandex.ru/album/40620828/track/148124289"


def test_yandex_info_album_and_playlists():
    _, factory = yandex()
    ymc = YandexMusic("k", factory)
    album = ymc.info(classify("https://music.yandex.ru/album/123"))
    assert album.title == "Meteora" and [t.title for t in album.tracks] == ["Foreword", "Numb"]
    assert album.tracks[1].url == "https://music.yandex.ru/album/123/track/2"

    pl = ymc.info(classify("https://music.yandex.ru/users/someone/playlists/3"))
    assert pl.kind == "yandex_playlist" and pl.title == "Плейлист"
    assert [(t.title, t.url) for t in pl.tracks] == [
        ("Раз", "https://music.yandex.ru/album/9/track/5"), ("Два", "https://music.yandex.ru/album/9/track/6")]
    assert ymc.client().calls[-1] == ("users_playlists", "3", "someone")

    by_uuid = ymc.info(classify("https://music.yandex.ru/playlists/ar.abc-1"))
    assert by_uuid.title == "По uuid" and by_uuid.tracks[0].url == "https://music.yandex.ru/track/7"


def test_yandex_download_best_mp3(tmp_path):
    infos = [FakeDownload("aac", 256), FakeDownload("mp3", 320, preview=True), FakeDownload("mp3", 192),
             FakeDownload("mp3", 320)]
    _, factory = yandex(track=make_track(infos=infos))
    dest = tmp_path / "in" / "input.mp3"
    YandexMusic("k", factory).download(TRACK, dest)
    assert dest.read_bytes() == b"mp3-320"
    assert infos[3].saved_to.endswith("input.mp3.part")
    assert list(dest.parent.iterdir()) == [dest]


def test_yandex_download_preview_only_needs_plus(tmp_path):
    _, factory = yandex(track=make_track(infos=[FakeDownload("mp3", 128, preview=True)]))
    with pytest.raises(MusicLinkError, match="нужна подписка Плюс"):
        YandexMusic("k", factory).download(TRACK, tmp_path / "a.mp3")
    _, factory = yandex(track=make_track(infos=[FakeDownload("mp3", 320)], available=False))
    with pytest.raises(MusicLinkError, match="нужна подписка Плюс"):
        YandexMusic("k", factory).download(TRACK, tmp_path / "a.mp3")


def test_yandex_download_failure_cleans_part(tmp_path):
    bad = FakeDownload("mp3", 320, fail=ym.NetworkError("Unavailable For Legal Reasons (451): b''"))
    _, factory = yandex(track=make_track(infos=[bad]))
    with pytest.raises(MusicLinkError, match="нужна подписка Плюс"):
        YandexMusic("k", factory).download(TRACK, tmp_path / "a.mp3")
    assert list(tmp_path.iterdir()) == []


def test_yandex_download_rejects_album(tmp_path):
    _, factory = yandex()
    with pytest.raises(MusicLinkError, match="только один трек"):
        YandexMusic("k", factory).download(classify("https://music.yandex.ru/album/1"), tmp_path / "a.mp3")


@pytest.mark.parametrize("kw, message", [
    ({"init_error": ym.UnauthorizedError("Session expired")}, ml.MSG_REJECTED),
    ({"error": ym.UnauthorizedError("x")}, ml.MSG_REJECTED),
    ({"error": ym.BadRequestError("no-rights")}, ml.MSG_NO_RIGHTS),
    ({"error": ym.NetworkError("Unknown error (451): b'{}'")}, ml.MSG_NO_RIGHTS),
    ({"error": ym.NetworkError("Connection reset")}, ml.MSG_UNAVAILABLE),
    ({"init_error": ym.TimedOutError()}, ml.MSG_UNAVAILABLE),
    ({"error": ym.NotFoundError("not-found")}, ml.MSG_NOT_FOUND),
])
def test_yandex_errors(kw, message):
    _, factory = yandex(**kw)
    with pytest.raises(MusicLinkError) as e:
        YandexMusic("secret-key-123", factory).info(TRACK)
    assert str(e.value) == message
    assert "secret-key-123" not in str(e.value)


@pytest.mark.parametrize("key", [None, "", "   "])
def test_yandex_without_key(key):
    made, factory = yandex()
    with pytest.raises(MusicLinkError, match="Впишите токен Яндекс Музыки в Настройках"):
        YandexMusic(key, factory).info(TRACK)
    assert made == []


def test_yandex_check():
    _, factory = yandex()
    YandexMusic("k", factory).check()

    def anonymous(key):
        c = FakeClient(key)
        c.me = NS(account=NS(uid=None))
        return c
    with pytest.raises(MusicLinkError, match="не приняла токен"):
        YandexMusic("k", anonymous).check()


# --------------------------------------------------------------------------- CLI

def test_cli_download(tmp_path, capsys):
    _, factory = yandex(track=make_track(infos=[FakeDownload("mp3", 320)]))
    dest = tmp_path / "input.mp3"
    url = "https://music.yandex.ru/album/40620828/track/148124289?utm_source=web"
    rc = ml.main(["download", url, str(dest)], env={"YANDEX_MUSIC_TOKEN": "cli-key"}, client_factory=factory)
    assert rc == 0 and dest.read_bytes() == b"mp3-320"


def test_cli_errors(tmp_path, capsys):
    _, factory = yandex()
    dest = str(tmp_path / "x.mp3")
    assert ml.main(["download", "https://music.yandex.ru/track/1", dest], env={}, client_factory=factory) == 1
    assert capsys.readouterr().err.strip().splitlines()[-1] == ml.MSG_NEED_LOGIN

    _, factory = yandex(error=ym.UnauthorizedError("bad"))
    assert ml.main(["download", "https://music.yandex.ru/track/1", dest],
                   env={"YANDEX_MUSIC_TOKEN": "cli-key"}, client_factory=factory) == 1
    err = capsys.readouterr().err
    assert err.strip().splitlines()[-1] == ml.MSG_REJECTED and "cli-key" not in err

    assert ml.main(["download", "https://youtu.be/x", dest], env={}, client_factory=factory) == 1
    assert "не ссылка Яндекс Музыки" in capsys.readouterr().err
    assert ml.main(["download", "https://vk.com/audio1_2", dest], env={}) == 1
    assert "ВКонтакте" in capsys.readouterr().err
    assert ml.main(["oops"], env={}) == 2


def test_cli_runs_as_module_without_network(tmp_path):
    import subprocess
    proc = subprocess.run([sys.executable, "-m", "karaoke_core.musiclink", "download",
                           "https://music.yandex.ru/track/1", str(tmp_path / "x.mp3")],
                          capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert proc.returncode == 1
    assert proc.stderr.strip().splitlines()[-1] == ml.MSG_NEED_LOGIN


def test_linkkind_is_frozen():
    with pytest.raises(Exception):
        LinkKind("ytdlp", "u", {}).kind = "x"
