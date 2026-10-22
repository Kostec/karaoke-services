// Чистая логика «Настройки → Куда выкладывать» (без DOM, под node-тесты): тело запроса по типу
// формы, сопоставление `field` ответа сервера с полем формы, подсказка про вход в Google.

/** Поля формы каждого типа (кроме «Название» и пароля). Яндекс Диск — webdav с preset=yandex. */
export const KIND_FIELDS = {
  smb: ['host', 'share', 'path', 'user'],
  local: ['path'],
  yandex: ['user', 'path'],
  webdav: ['url', 'user', 'path'],
  gdrive: ['client_id', 'path'],
};
const PASS_KINDS = new Set(['smb', 'yandex', 'webdav', 'gdrive']);
const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]']);

/** Тип формы для сохранённого хранилища: webdav с preset=yandex — «Яндекс Диск». */
export function formKind(t) {
  return t.kind === 'webdav' && t.preset === 'yandex' ? 'yandex' : t.kind;
}

/** Тело POST/PUT/test из значений формы типа `kind`; пустой пароль не отправляется («не менять»). */
export function targetBody(kind, values, { id } = {}) {
  const b = {};
  if (id) b.id = id;
  if (kind === 'yandex') Object.assign(b, { kind: 'webdav', preset: 'yandex' });
  else b.kind = kind;
  b.name = String(values.name ?? '').trim();
  for (const key of KIND_FIELDS[kind] || []) b[key] = String(values[key] ?? '').trim();
  if (PASS_KINDS.has(kind) && values.password) b['password'] = values.password;
  return b;
}

/** Тело «Проверить» для сохранённого хранилища из списка (сервер подставит свой пароль по id). */
export function savedBody(t) {
  return targetBody(formKind(t), t, { id: t.id });
}

/** Поле формы для `field` из ответа об ошибке: имя поля, `folder` (обзор папок) или null. */
export function fieldTarget(field, kind) {
  if (!field) return null;
  if (field === 'name') return 'name';
  if (field === 'password') return PASS_KINDS.has(kind) ? 'password' : null;
  if (!(KIND_FIELDS[kind] || []).includes(field)) return null;
  return kind === 'local' && field === 'path' ? 'folder' : field;
}

/** Страница открыта не с localhost/127.0.0.1 — Google не вернёт вход сюда, нужна подсказка. */
export function needsLocalHint(hostname) {
  return !LOOPBACK.has(hostname);
}

/** Те же адрес и логин, что у сохранённого `t` с паролем, — пустой пароль значит «не менять». */
export function sameAccount(kind, values, t) {
  if (!t || !t.has_password) return false;
  const v = (k) => String(values[k] ?? '').trim();
  if (kind === 'gdrive') return v('client_id') === t.client_id;
  if (kind === 'smb') return v('host') === t.host && v('share').replace(/^\/+|\/+$/g, '') === t.share && v('user') === t.user;
  if (kind === 'yandex') return v('user') === t.user;
  if (kind === 'webdav') return v('url').replace(/\/+$/, '') === t.url && v('user') === t.user;
  return false;
}
