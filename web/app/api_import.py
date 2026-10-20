"""Импорт готовой песни UltraStar (Решения §4): разбор источника и постановка задания ``import``.

Шаг 1 — ``POST /api/import/inspect``: usdb-песня, загруженные файлы (zip или .txt + аудио +
обложка) или ссылка (zip, GitHub) раскладываются в ``imports/<token>/files/``, разбор —
в ``imports/<token>/meta.json``; ответ — найденные песни. Ничего не ставится в очередь.
Шаг 2 — ``POST /api/jobs/import``: файлы выбранной песни копируются во вход задания
(``song.txt`` — исходные байты), ставится задание ``import``. Распаковка живёт час.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import secrets
import shutil
import time
import urllib.parse
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, File, Form, Request, UploadFile

from karaoke_core import naming, songpack, ultrastar
from karaoke_core.http import HttpError
from karaoke_core.paths import DataPaths, INPUT_AUDIO, INPUT_COVER_STEM

from .api_jobs import CHUNK, MB, Staging, copy_limited, ctx_of, download_cover, is_mp3, queue_duplicate
from .api_usdb import usdb_api_error
from .context import ApiError, AppContext, song_key
from .params import max_import_mb
from .usdb import UsdbError

log = logging.getLogger("karaoke.web")
router = APIRouter(tags=["Импорт"])

IMPORT_TTL_S = 3600
SOURCES = ("usdb", "files", "url")
META = "meta.json"
FILES = "files"
INPUT_TXT = "song.txt"
INPUT_IMPORT_AUDIO_STEM = "audio"  # audio.<ext> — звук из архива

NO_SONGS = "В архиве нет песен UltraStar (.txt с #TITLE и нотами)"
EXPIRED = "Загрузка устарела, загрузите заново"
NEED_AUDIO = "Нужен звук: загрузите mp3 или вставьте ссылку на YouTube"
WARN_SYNC = "Ноты сделаны под конкретную запись — с другой версией слова могут разъехаться"
ZIP_SIG = b"PK\x03\x04"

_GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?"
                        r"(?:/tree/([^/?#]+)((?:/[^?#]*)?))?/?(?:[?#].*)?\Z", re.I)


# --------------------------------------------------------------------------- уборка

def _age_s(folder: Path) -> float:
    meta = folder / META
    try:
        stamp = (meta if meta.is_file() else folder).stat().st_mtime
    except OSError:
        return 0.0
    return time.time() - stamp


def purge_imports(paths: DataPaths, max_age_s: float = IMPORT_TTL_S) -> int:
    """Удалить распаковки ``imports/*`` старше часа (по времени записи ``meta.json``)."""
    root, removed = paths.imports_root, 0
    if not root.is_dir():
        return 0
    for folder in root.iterdir():
        if folder.is_dir() and _age_s(folder) > max_age_s:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed


# --------------------------------------------------------------------------- приём источника

def _save_upload(upload: UploadFile, dest: Path, limit_mb: int, total: list[int], too_big: str) -> None:
    """Сохранить загрузку; ``total`` — байты всех файлов этой загрузки, больше лимита — 413."""
    with open(dest, "wb") as out:
        while chunk := upload.file.read(CHUNK):
            total[0] += len(chunk)
            if total[0] > limit_mb * MB:
                raise ApiError(413, too_big, field="files")
            out.write(chunk)


def _extract(ctx: AppContext, zip_path: Path, dest: Path) -> None:
    try:
        songpack.safe_extract(zip_path, dest, 2 * max_import_mb(ctx) * MB)
    except songpack.PackError as e:
        raise ApiError(400, e.message) from None
    finally:
        zip_path.unlink(missing_ok=True)


def _from_files(ctx: AppContext, work: Path, files: list[UploadFile]) -> None:
    files = [f for f in files if f is not None and f.filename]
    if not files:
        raise ApiError(400, "Загрузите zip или файлы песни", field="files")
    limit_mb = max_import_mb(ctx)
    total = [0]
    dest = work / FILES
    dest.mkdir()
    if len(files) == 1 and (files[0].file.read(4) == ZIP_SIG or files[0].filename.lower().endswith(".zip")):
        files[0].file.seek(0)
        zip_path = work / "upload.zip"
        _save_upload(files[0], zip_path, limit_mb, total, f"Архив больше {limit_mb} МБ")
        _extract(ctx, zip_path, dest)
        return
    # Сначала проверить все пути: плохой путь — 400 до записи хоть одного файла.
    planned: list[tuple[UploadFile, str]] = []
    seen: set[str] = set()
    for f in files:
        if f.filename.startswith(("/", "\\")):
            raise ApiError(400, BAD_PATH, field="files")
        rel = _safe_rel(f.filename, BAD_PATH, "files")  # папка из браузера: «папка/песня/файл»
        parts = rel.split("/")
        name = parts[-1]
        if (not name or any(p.startswith(".") for p in parts)
                or PurePosixPath(name).suffix.lower() not in songpack.ALLOWED_EXTS):
            if name.lower().endswith(".zip"):
                raise ApiError(400, "Загрузите один zip или файлы песни без архива", field="files")
            continue  # не файл песни (или скрытая папка) — молча пропускаем, как при распаковке
        if rel.casefold() in seen:
            raise ApiError(400, f"Два файла с именем «{rel}» — оставьте один или загрузите zip",
                           field="files")
        seen.add(rel.casefold())
        planned.append((f, rel))
    # файл и папка с одним именем («x.txt» и «x.txt/song.txt») не уживутся на диске
    dirs = {"/".join(rel.casefold().split("/")[:i]) for _, rel in planned for i in range(1, rel.count("/") + 1)}
    clash = next((rel for _, rel in planned if rel.casefold() in dirs), None)
    if clash:
        raise ApiError(400, f"«{clash}» — и файл, и папка с тем же именем; переименуйте одно из них",
                       field="files")
    for f, rel in planned:
        f.file.seek(0)
        target = dest / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _save_upload(f, target, limit_mb, total, f"Файлы вместе больше {limit_mb} МБ")
        except OSError:  # слишком длинное имя и прочее, чего не примет файловая система
            raise ApiError(400, f"Не удалось сохранить «{rel}» — слишком длинное или недопустимое имя",
                           field="files") from None


BAD_PATH_URL = "Недопустимая папка в ссылке на GitHub"
BAD_PATH = "Недопустимый путь в загрузке"


def _safe_rel(raw: str, message: str, field: str) -> str:
    """Относительный путь POSIX: ``\\`` → ``/``, пустые и ``.`` части убраны; ``..``, буква диска,
    NUL → 400 до любой записи."""
    text = raw.replace("\\", "/")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if "\0" in text or any(p == ".." or re.match(r"[A-Za-z]:", p) for p in parts):
        raise ApiError(400, message, field=field)
    return "/".join(parts)


def _safe_subdir(raw: str) -> str:
    """Папка из ``/tree/<ветка>/<папка>``: раскодировать и проверить, как путь файла загрузки."""
    return _safe_rel(urllib.parse.unquote(raw), BAD_PATH_URL, "url")


def _inside(work: Path, rel: str) -> Path:
    """Путь от ``imports/<token>`` обязан лежать внутри ``imports/<token>/files``, иначе 400."""
    root = (work / FILES).resolve()
    path = (work / rel).resolve()
    if not path.is_relative_to(root):
        raise ApiError(400, BAD_PATH)
    return path


def _github_zip(ctx: AppContext, url: str) -> tuple[str, str] | None:
    """Ссылка на GitHub → (codeload-архив, папка внутри репозитория); не GitHub — ``None``."""
    m = _GITHUB_RE.match(url)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    branch = urllib.parse.unquote(m.group(3)) if m.group(3) else None
    sub = _safe_subdir(m.group(4) or "")
    if branch is not None and (branch in (".", "..") or "\\" in branch or "\0" in branch):
        raise ApiError(400, BAD_PATH_URL, field="url")
    if not branch:
        try:
            resp = ctx.http.request("GET", f"https://api.github.com/repos/{owner}/{repo}",
                                    headers={"Accept": "application/vnd.github+json"})
            branch = json.loads(resp.body.decode("utf-8")).get("default_branch")
        except (HttpError, ValueError, AttributeError):
            branch = None
        if not branch:
            raise ApiError(400, "Репозиторий GitHub не найден или недоступен", field="url")
    return f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}", sub


def _from_url(ctx: AppContext, work: Path, url: str) -> str:
    """Скачать zip по ссылке и распаковать; вернуть папку поиска песен от ``files/``."""
    url = (url or "").strip()
    if not re.match(r"https?://", url, re.I):
        raise ApiError(400, "Вставьте ссылку http(s) на zip или GitHub", field="url")
    sub = ""
    gh = _github_zip(ctx, url)
    if gh:
        url, sub = gh
    limit_mb = max_import_mb(ctx)
    zip_path = work / "download.zip"
    try:
        ctx.http.download(url, zip_path, max_bytes=limit_mb * MB, timeout=300)
    except HttpError as e:
        zip_path.unlink(missing_ok=True)
        if e.too_large:
            raise ApiError(413, f"Архив больше {limit_mb} МБ", field="url") from None
        raise ApiError(400, f"Не удалось скачать архив: {e}", field="url") from None
    with open(zip_path, "rb") as f:
        if f.read(4) != ZIP_SIG:
            zip_path.unlink(missing_ok=True)
            raise ApiError(400, "По ссылке не zip-архив", field="url")
    dest = work / FILES
    dest.mkdir()
    _extract(ctx, zip_path, dest)
    if not gh:
        return ""
    tops = [p for p in dest.iterdir() if p.is_dir()]  # codeload кладёт всё в <repo>-<ветка>/
    base = PurePosixPath(tops[0].name, *PurePosixPath(sub).parts) if len(tops) == 1 else PurePosixPath(sub)
    if not (dest / base).is_dir():
        raise ApiError(400, NO_SONGS)
    return base.as_posix() if str(base) != "." else ""


def _has_instrumental(txt_path: Path) -> bool:
    """В заголовке ``#INSTRUMENTAL`` и такой файл лежит рядом с .txt (без учёта регистра)."""
    try:
        value = ultrastar.parse(txt_path.read_bytes()).header("INSTRUMENTAL")
    except (OSError, ValueError):
        return False
    return songpack.resolve_file(txt_path.parent, value, songpack.AUDIO_EXTS) is not None


def _from_usdb(ctx: AppContext, work: Path, usdb_id: int | None) -> list[songpack.FoundSong]:
    if not usdb_id or usdb_id <= 0:
        raise ApiError(400, "Укажите id песни в usdb", field="usdb_id")
    client = ctx.usdb()
    try:
        song = client.fetch_song(usdb_id)
    except UsdbError as e:
        raise usdb_api_error(e) from None
    dest = work / FILES
    dest.mkdir()
    (dest / INPUT_TXT).write_bytes(song.txt)
    found = songpack.find_songs(dest)
    if not found:
        raise ApiError(400, NO_SONGS)
    s = found[0]
    youtube = list(s.youtube)
    for link in song.youtube:
        if link not in youtube:
            youtube.append(link)
    # обложку скачивает постановка задания: сначала co= из #VIDEO, иначе обложка usdb
    return [dataclasses.replace(s, youtube=youtube, cover_url=s.cover_url or song.cover_url)]


# --------------------------------------------------------------------------- ответ

def _warnings(s: dict) -> list[str]:
    if s["audio_rel"]:
        return []
    return [WARN_SYNC] if s["youtube"] else [NEED_AUDIO]


def _public(ctx: AppContext, s: dict) -> dict:
    return {"index": s["index"], "artist": s["artist"], "title": s["title"],
            "language": s["language"], "duet": s["duet"],
            "audio": PurePosixPath(s["audio_rel"]).name if s["audio_rel"] else None,
            "cover": bool(s["cover_rel"] or s["cover_url"]), "youtube": s["youtube"],
            "has_instrumental": s["has_instrumental"],
            "existing_song_id": ctx.existing_song_id(s["artist"], s["title"]),
            "warnings": _warnings(s)}


@router.post("/api/import/inspect", summary="Разобрать источник импорта",
             description="multipart: `source=usdb|files|url`, `usdb_id` | `url` | `files`. "
                         "Распаковка хранится час; ответ — найденные песни и `token` для `/api/jobs/import`.")
def inspect(request: Request, source: str = Form(...), usdb_id: int | None = Form(None),
            url: str | None = Form(None), files: list[UploadFile] = File(default=[])):
    ctx = ctx_of(request)
    if source not in SOURCES:
        raise ApiError(400, "Источник: usdb, files или url", field="source")
    purge_imports(ctx.paths)
    import_id = secrets.token_hex(16)
    work = ctx.paths.import_dir(import_id)
    work.mkdir(parents=True)
    try:
        root = ""
        if source == "usdb":
            found = _from_usdb(ctx, work, usdb_id)
        else:
            if source == "files":
                _from_files(ctx, work, files)
            else:
                root = _from_url(ctx, work, url or "")
            found = songpack.find_songs(_inside(work, f"{FILES}/{root}"))
        if not found:
            raise ApiError(400, NO_SONGS)
        prefix = f"{FILES}/{root}/" if root else f"{FILES}/"
        songs = [{"index": i, "txt_rel": prefix + s.txt_rel, "artist": s.artist, "title": s.title,
                  "language": s.language, "duet": s.duet,
                  "audio_rel": prefix + s.audio_rel if s.audio_rel else None,
                  "cover_rel": prefix + s.cover_rel if s.cover_rel else None,
                  "youtube": list(s.youtube), "cover_url": s.cover_url,
                  "has_instrumental": _has_instrumental(work / prefix / s.txt_rel)}
                 for i, s in enumerate(found)]
        meta = {"token": import_id, "source": source, "created": time.time(), "songs": songs}
        if source == "usdb":
            meta["usdb_id"] = usdb_id
        (work / META).write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return {"token": import_id, "source": source, "songs": [_public(ctx, s) for s in songs]}


# --------------------------------------------------------------------------- постановка

MAX_YOUTUBE_ALTERNATIVES = 5


def _unique_links(links: list[str] | None) -> list[str]:
    """Ссылки песни (#VIDEO, комментарии usdb) без пустых и повторов, в исходном порядке."""
    out: list[str] = []
    for raw in links or []:
        u = (raw or "").strip()
        if u and u not in out:
            out.append(u)
    return out


def _load_meta(ctx: AppContext, token: str) -> tuple[Path, dict]:
    try:
        work = ctx.paths.import_dir(token)
    except ValueError:
        raise ApiError(410, EXPIRED) from None
    meta_path = work / META
    if not meta_path.is_file() or _age_s(work) > IMPORT_TTL_S:
        shutil.rmtree(work, ignore_errors=True)
        raise ApiError(410, EXPIRED)
    return work, json.loads(meta_path.read_text("utf-8"))


@router.post("/api/jobs/import", status_code=201, tags=["Задания"], summary="Импортировать песню",
             description="По `token` и `index` из inspect: вход — songs/<A>/<A - T>/jobs/<id>/in "
                         "(`song.txt` без изменений, звук, обложка); задание `import`.")
def import_job(request: Request, token: str = Form(...), index: int = Form(...),
               artist: str = Form(""), title: str = Form(""),
               audio: UploadFile | None = File(None), youtube_url: str | None = Form(None),
               instrumental: bool = Form(False), replace: bool = Form(False),
               song_id: str | None = Form(None)):
    ctx = ctx_of(request)
    work, meta = _load_meta(ctx, token)
    songs = meta.get("songs") or []
    if not 0 <= index < len(songs):
        raise ApiError(400, "Нет такой песни в загрузке", field="index")
    s = songs[index]
    artist, title = artist.strip(), title.strip()
    if not artist or not title:
        raise ApiError(400, "Укажите исполнителя и название", field="artist" if not artist else "title")
    key = song_key(artist, title)
    queue_duplicate(ctx, "generate", key=key)
    queue_duplicate(ctx, "import", key=key)

    source = ctx.find_song(song_id) if song_id else None
    existing = ctx.find_by_name(artist, title)
    if existing and not replace and not (source and existing.song_id == source.song_id):
        raise ApiError(409, "Такая песня уже есть в папке результата", song_id=existing.song_id)

    has_audio = audio is not None and bool(audio.filename)
    if has_audio and not is_mp3(audio.file.read(4)):
        raise ApiError(400, "Это не mp3-файл", field="audio")
    link = (youtube_url or "").strip() or None
    if link and not re.match(r"https?://", link, re.I):
        raise ApiError(400, "Ссылка на YouTube должна начинаться с http(s)://", field="youtube_url")
    alternatives: list[str] = []
    from_user = False
    if not has_audio and not s["audio_rel"]:
        song_links = _unique_links(s["youtube"])
        link = link or (song_links[0] if song_links else None)
        if not link:
            raise ApiError(400, NEED_AUDIO, field="audio")
        # фронт присылает ссылку песни как есть: своя — только та, которой нет в разборе
        from_user = link not in song_links
        if not from_user:
            alternatives = [u for u in song_links if u != link][:MAX_YOUTUBE_ALTERNATIVES]
    else:
        link = None

    rel_dir = naming.song_dir(artist, title)
    storage = ctx.storage()
    staging = Staging(ctx, rel_dir)
    try:
        shutil.copyfile(_inside(work, s["txt_rel"]), staging.path("txt", INPUT_TXT))
        if has_audio:
            audio.file.seek(0)
            copy_limited(audio.file, staging.path("audio", INPUT_AUDIO), ctx.max_upload_mb, "audio")
        elif s["audio_rel"]:
            ext = PurePosixPath(s["audio_rel"]).suffix.lower()
            shutil.copyfile(_inside(work, s["audio_rel"]), staging.path("audio", f"{INPUT_IMPORT_AUDIO_STEM}{ext}"))
        if s["cover_rel"]:
            ext = PurePosixPath(s["cover_rel"]).suffix.lower().replace(".jpeg", ".jpg")
            shutil.copyfile(_inside(work, s["cover_rel"]), staging.path("cover", f"{INPUT_COVER_STEM}{ext}"))
        elif s.get("cover_url"):
            name = download_cover(ctx, s["cover_url"], staging.dir)  # не скачалась — без обложки
            if name:
                staging.path("cover", name)
    except BaseException:
        staging.discard()
        raise

    replace_dir = existing.rel_dir if existing else (source.rel_dir if source else None)
    params: dict = {"source": meta["source"]}
    if meta["source"] == "usdb":
        params["usdb_id"] = meta.get("usdb_id")
    if link:
        params.update(youtube_url=link, youtube_alternatives=alternatives, youtube_from_user=from_user)
    params.update(instrumental=bool(instrumental), rel_dir=rel_dir, replace=bool(replace_dir),
                  replace_rel_dir=replace_dir, target_id=storage.target_id)
    ref_id = source.song_id if source else (existing.song_id if existing else None)
    return staging.enqueue("import", {"artist": artist, "title": title, "song_id": ref_id}, params).to_dict()
