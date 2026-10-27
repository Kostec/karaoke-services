"""Резервная копия настроек (истории 66–68): теги со связями, хранилища, основная цель,
логин usdb, Telegram без токена и зеркала — одним JSON-файлом.

Секреты не выгружаются по построению: в файл попадают только поля из явных списков ниже
(пароли SMB/WebDAV, Client secret и OAuth Google, пароль usdb, ключ Яндекс Музыки и ключ
Telegram-бота в них нет). Загрузка ничего не удаляет и сохранённых секретов не трогает:
теги сопоставляются по названию, хранилища — по ``id`` (от него зависят ``song_id`` песен),
зеркала — по паре «откуда → куда».
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .db import (DEFAULT_TAG_COLOR, LOCAL_OUTPUT_MOUNT, LOCAL_TARGET_ID, TAG_COLORS, TAG_NAME_MAX,
                 TARGET_KINDS, Mirror, Settings, Tags, Target, TelegramSettings, UsdbAccount, default_target_name, now,
                 tag_name_key)

__all__ = ["FORMAT", "VERSION", "NOT_SETTINGS", "TARGET_FIELDS", "BackupError", "ImportPlan",
           "export_settings", "read_backup", "plan_import", "apply_import"]

FORMAT = "karaoke-services-settings"
VERSION = 1
NOT_SETTINGS = "Это не файл настроек karaoke-services"
# Единственный список полей хранилища, которые попадают в файл (без secret/token).
TARGET_FIELDS = ("id", "name", "kind", "path", "host", "share", "user", "url", "preset", "client_id")
TELEGRAM_EVENTS = ("on_done", "on_failed", "on_queue_empty")
LOCAL_ROOTS = ("host", "output")  # как api_targets.BROWSE_ROOTS: /host и /output
_TARGET_ID = re.compile(r"^t_[A-Za-z0-9_-]{1,40}$")


class BackupError(ValueError):
    """Файл — не резервная копия этого сервиса (или испорчен)."""

    def __init__(self, message: str = NOT_SETTINGS):
        super().__init__(message)


# --------------------------------------------------------------------------- выгрузка

def _song_links(tags: Tags) -> dict[str, list[str]]:
    """Ключи песен каждого тега: ``{tag_id: [song_key, …]}`` (по алфавиту)."""
    out: dict[str, list[str]] = {}
    for row in tags.conn.execute("SELECT tag_id, song_key FROM song_tags ORDER BY song_key"):
        out.setdefault(row[0], []).append(row[1])
    return out


def export_settings(settings: Settings, tags: Tags) -> dict:
    """Содержимое файла резервной копии (только поля из явных списков, без секретов)."""
    links = _song_links(tags)
    tg = settings.get_telegram()
    return {
        "format": FORMAT,
        "version": VERSION,
        "created_at": now(),
        "default_target_id": settings.get_default_target_id(),
        "targets": [{k: getattr(t, k) for k in TARGET_FIELDS}
                    for t in settings.get_targets() if not t.builtin],
        "tags": [{"name": t.name, "color": t.color, "songs": links.get(t.id, [])} for t in tags.list()],
        "usdb": {"user": settings.get_usdb().user},
        "telegram": {"chat_id": tg.chat_id, **{k: getattr(tg, k) for k in TELEGRAM_EVENTS}},
        "mirrors": [{"from_target": m.from_target, "to_target": m.to_target, "enabled": m.enabled}
                    for m in settings.get_mirrors()],
    }


# --------------------------------------------------------------------------- разбор файла

def read_backup(raw: bytes) -> dict:
    """JSON файла; не JSON или не объект — ``BackupError``. Содержимое проверяет ``plan_import``."""
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise BackupError() from None
    if not isinstance(data, dict):
        raise BackupError()
    return data


def _check(ok: bool) -> None:
    if not ok:
        raise BackupError()


def _str(value, default: str = "") -> str:
    if value is None:
        return default
    _check(isinstance(value, str))
    return value.strip()


def _list(data: dict, key: str) -> list[dict]:
    value = data.get(key)
    if value is None:
        return []
    _check(isinstance(value, list) and all(isinstance(v, dict) for v in value))
    return value


def _obj(data: dict, key: str) -> dict:
    value = data.get(key)
    if value is None:
        return {}
    _check(isinstance(value, dict))
    return value


def _bool(value, default: bool) -> bool:
    if value is None:
        return default
    _check(isinstance(value, bool))
    return value


def _target_path(kind: str, raw: str) -> str:
    """Путь хранилища по правилам ``api_targets`` (``_rel_path``/``_local_path``): без ``..``, ``.``
    и двоеточий; у ``local`` — папка внутри ``/host`` или ``/output``, но не сам ``/output``.
    Иначе весь файл отклоняется — ``BackupError``."""
    path = raw.replace("\\", "/")
    parts = [p for p in path.split("/") if p]
    _check(not any(p in ("..", ".") for p in parts) and ":" not in path)
    if kind != "local":
        return "/".join(parts)
    _check(bool(parts) and parts[0] in LOCAL_ROOTS)
    local = "/" + "/".join(parts)
    _check(local != LOCAL_OUTPUT_MOUNT)
    return local


def _identity(t: Target) -> tuple:
    """Адрес и логин, как ``api_targets._identity``: при их смене прежний секрет не подставляется."""
    if t.kind == "gdrive":
        return (t.kind, t.client_id)
    return (t.kind, t.host, t.share, t.user, t.url.rstrip("/"))


@dataclass
class _FileTag:
    name: str
    color: str
    songs: list[str]


def _parse(data: dict) -> tuple[list[Target], list[_FileTag], list[Mirror], dict, dict, str]:
    """Проверка структуры файла целиком (до любых изменений); чужое или битое — ``BackupError``."""
    _check(data.get("format") == FORMAT and data.get("version") == VERSION)
    targets = []
    for t in _list(data, "targets"):
        values = {k: _str(t.get(k)) for k in TARGET_FIELDS}
        _check(values["kind"] in TARGET_KINDS)
        _check(values["id"] == LOCAL_TARGET_ID or bool(_TARGET_ID.match(values["id"])))
        if values["id"] != LOCAL_TARGET_ID:  # встроенное из файла пропускается в plan_import
            values["path"] = _target_path(values["kind"], values["path"])
        targets.append(Target(**values))
    file_tags = []
    for t in _list(data, "tags"):
        name = " ".join(_str(t.get("name")).split())
        _check(bool(name) and len(name) <= TAG_NAME_MAX)
        color = _str(t.get("color"), DEFAULT_TAG_COLOR)
        songs = t.get("songs") or []
        _check(isinstance(songs, list) and all(isinstance(k, str) and k for k in songs))
        file_tags.append(_FileTag(name, color if color in TAG_COLORS else DEFAULT_TAG_COLOR, songs))
    mirrors = [Mirror(from_target=_str(m.get("from_target")), to_target=_str(m.get("to_target")),
                      enabled=_bool(m.get("enabled"), True)) for m in _list(data, "mirrors")]
    usdb = _obj(data, "usdb")
    usdb = {"user": _str(usdb.get("user"))}
    tg = _obj(data, "telegram")
    tg = {"chat_id": _str(tg.get("chat_id")),
          **{k: _bool(tg.get(k), getattr(TelegramSettings(), k)) for k in TELEGRAM_EVENTS}}
    default_id = _str(data.get("default_target_id"))
    return targets, file_tags, mirrors, usdb, tg, default_id


# --------------------------------------------------------------------------- план

@dataclass
class ImportPlan:
    """Что сделает загрузка. Строится ``plan_import`` без изменений, исполняется ``apply_import``."""
    new_targets: list[Target] = field(default_factory=list)
    changed_targets: list[Target] = field(default_factory=list)
    new_tags: list[_FileTag] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (song_key, tag_name_key)
    new_mirrors: list[Mirror] = field(default_factory=list)
    default_target: Target | None = None
    usdb_user: str = ""
    telegram: TelegramSettings | None = None
    ask_pass: list[str] = field(default_factory=list)
    ask_google: list[str] = field(default_factory=list)
    tg_key_missing: bool = False
    usdb_pass_missing: bool = False
    ym_key_missing: bool = False

    def to_dict(self) -> dict:
        """Ответ API: счётчики и списки имён (секретов здесь нет)."""
        return {
            "tags_added": len(self.new_tags),
            "tag_links_added": len(self.links),
            "targets_added": len(self.new_targets),
            "targets_updated": len(self.changed_targets),
            "mirrors_added": len(self.new_mirrors),
            "usdb_user_set": bool(self.usdb_user),
            "needs_password": list(self.ask_pass),
            "needs_google": list(self.ask_google),
            "default_target": _name(self.default_target) if self.default_target else None,
            "telegram_set": self.telegram is not None,
            "telegram_needs_token": self.tg_key_missing,
            "usdb_needs_password": self.usdb_pass_missing,
            "yandex_needs_token": self.ym_key_missing,
        }


def _name(target: Target) -> str:
    return target.name or default_target_name(target)


def _public_fields(target: Target) -> dict:
    return {k: getattr(target, k) for k in TARGET_FIELDS}


def plan_import(data: dict, settings: Settings, tags: Tags) -> ImportPlan:
    """План загрузки файла ``data`` (см. ``read_backup``); ничего не меняет.
    Чужой или битый файл — ``BackupError``."""
    file_targets, file_tags, file_mirrors, usdb, tg, default_id = _parse(data)
    plan = ImportPlan()

    # хранилища — по id; встроенное «Локальное хранилище» не трогается
    current = {t.id: t for t in settings.get_targets()}
    after: dict[str, Target] = dict(current)
    seen: list[str] = []
    for t in file_targets:
        if t.id == LOCAL_TARGET_ID or t.id in seen:
            continue
        seen.append(t.id)
        old = current.get(t.id)
        if old is None:
            plan.new_targets.append(t)
            after[t.id] = t
        else:
            # тот же адрес и логин — прежние пароль и вход Google (None = «не менять»),
            # другие — секреты сбрасываются: прежний пароль не уйдёт на чужой сервер
            same = _identity(old) == _identity(t)
            kept = (None, None) if same else ("", "")
            if _public_fields(old) != _public_fields(t):
                plan.changed_targets.append(Target(**{**_public_fields(t), "secret": kept[0], "token": kept[1]}))
            after[t.id] = Target(**{**_public_fields(t), "secret": old.secret if same else "",
                                    "token": old.token if same else ""})
    for t in [after[i] for i in seen]:
        if t.kind == "gdrive" and not (t.token and t.secret):
            plan.ask_google.append(_name(t))
        elif t.kind in ("smb", "webdav") and t.user and not t.secret:
            plan.ask_pass.append(_name(t))
    if default_id in after and default_id != settings.get_default_target_id():
        plan.default_target = after[default_id]

    # теги — по названию (без регистра, ё = е); цвет существующего не меняется
    known = {tag_name_key(t.name): t.id for t in tags.list()}
    linked = {(row[0], row[1]) for row in tags.conn.execute("SELECT song_key, tag_id FROM song_tags")}
    planned_tags: set[str] = set()
    planned_links: set[tuple[str, str]] = set()
    for t in file_tags:
        key = tag_name_key(t.name)
        if key not in known and key not in planned_tags:
            planned_tags.add(key)
            plan.new_tags.append(t)
        for song in t.songs:
            link = (song, key)
            if link in planned_links or (key in known and (song, known[key]) in linked):
                continue
            planned_links.add(link)
            plan.links.append(link)

    # зеркала — по паре хранилищ (и обратной); оба хранилища должны быть после загрузки
    pairs = {frozenset((m.from_target, m.to_target)) for m in settings.get_mirrors()}
    for m in file_mirrors:
        pair = frozenset((m.from_target, m.to_target))
        if m.from_target == m.to_target or m.from_target not in after or m.to_target not in after \
                or pair in pairs:
            continue
        pairs.add(pair)
        plan.new_mirrors.append(m)

    # usdb: логин ставится, только если своего ещё нет (пароль чужой учётки не подходит)
    account = settings.get_usdb()
    if usdb["user"] and not account.user:
        plan.usdb_user = usdb["user"]
    plan.usdb_pass_missing = bool(plan.usdb_user or account.user) and not account.password

    # Telegram: чат и события; ключ бота остаётся прежним
    saved = settings.get_telegram()
    if tg["chat_id"] and (tg["chat_id"], *[tg[k] for k in TELEGRAM_EVENTS]) != \
            (saved.chat_id, *[getattr(saved, k) for k in TELEGRAM_EVENTS]):
        plan.telegram = TelegramSettings(None, tg["chat_id"], *[tg[k] for k in TELEGRAM_EVENTS])
    plan.tg_key_missing = bool(tg["chat_id"] or saved.chat_id) and not saved.bot_token

    # Яндекс Музыка — только ключ доступа, в файл не попадает
    plan.ym_key_missing = settings.get_yandex() is None
    return plan


# --------------------------------------------------------------------------- применение

def apply_import(plan: ImportPlan, settings: Settings, tags: Tags) -> None:
    """Исполнить план: только добавляет и обновляет, ничего не удаляет; пароли и токены
    существующих хранилищ, usdb, Яндекса и Telegram остаются прежними."""
    if plan.new_targets:
        # save_target не создаёт хранилище с заданным id, а id нужен прежний (от него song_id)
        settings._write_targets([*settings.get_targets(), *[Target(**_public_fields(t))
                                                           for t in plan.new_targets]])
    for t in plan.changed_targets:
        settings.save_target(t)  # secret/token None — прежние, "" — сброшены (адрес или логин другие)
    if plan.default_target is not None:
        settings.set_default_target_id(plan.default_target.id)

    for t in plan.new_tags:
        tags.create(t.name, t.color)
    ids = {tag_name_key(t.name): t.id for t in tags.list()}
    by_tag: dict[str, list[str]] = {}
    for song, key in plan.links:
        if key in ids:
            by_tag.setdefault(ids[key], []).append(song)
    for tag_id, songs in by_tag.items():
        tags.change_for_songs(songs, [tag_id], [])

    for m in plan.new_mirrors:
        settings.save_mirror(Mirror(from_target=m.from_target, to_target=m.to_target, enabled=m.enabled))
    if plan.usdb_user:
        settings.set_usdb(UsdbAccount(plan.usdb_user, None))
    if plan.telegram is not None:
        settings.set_telegram(plan.telegram)
