// Ссылки на музыку: чистая логика без DOM — какая это ссылка (архив песен или музыка),
// подсказки по ответу POST /api/link/inspect, ошибка «нет токена Яндекс Музыки».
// DOM и сеть — в new-song.js, import.js, settings.js.

/** Код ошибки сервера: ссылка на Яндекс Музыку, а токена в «Настройках» нет. */
export const NO_YM_CODE = 'yandex_no_token';
export const SETTINGS_LINK_TEXT = 'Открыть Настройки';
export const LINK_SERVICES = 'YouTube, VK-видео, RuTube, SoundCloud, Яндекс Музыка';
export const NEED_LINK = 'Вставьте ссылку';
export const NO_TRACKS = 'По ссылке не нашлось ни одного трека';

/** Ошибка API — «впишите токен Яндекс Музыки» (показать ссылку на #settings). */
export function isYandexNoToken(e) {
  return e?.data?.code === NO_YM_CODE;
}

/**
 * Что вставили во вкладке «Импорт → Ссылка»: 'pack' — zip-архив или GitHub (готовые песни,
 * /api/import/inspect), 'music' — всё остальное (трек/альбом/плейлист на генерацию, /api/link/inspect).
 * Zip — путь на «.zip», codeload.github.com или любая ссылка на github.com (репозиторий, папка).
 */
export function linkSource(raw) {
  try {
    return sourceOf(raw);
  } catch {
    return 'music'; // никогда не бросает: сервер ответит понятным текстом
  }
}

function sourceOf(raw) {
  const s = String(raw ?? '').trim();
  if (!s) return 'music';
  let u;
  try {
    u = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(s) ? s : `https://${s}`);
  } catch {
    return 'music'; // сервер ответит понятным текстом про вид ссылки
  }
  const host = u.hostname.toLowerCase().replace(/^www\./, '');
  if (host === 'github.com' || host === 'codeload.github.com') return 'pack';
  if (/\.zip$/i.test(safeDecode(u.pathname))) return 'pack';
  return 'music';
}

/** decodeURIComponent без исключений: битый «%» — путь как есть. */
function safeDecode(s) {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

/**
 * Обложка со ссылки, которая реально уйдёт в generate (``cover_url``), или null:
 * своей обложки (файл формы или из тегов mp3) нет, звук — по ссылке (mp3 не выбран),
 * и «Получить» был именно для текущей ссылки. Её же показывает превью «Обложка со ссылки».
 */
export function linkCoverUrl({ ownCover = null, audioFile = null, link = null, input = '', thumb = null } = {}) {
  if (ownCover || audioFile || !thumb || !link?.url) return null;
  const s = String(input ?? '').trim();
  return s && link.input === s ? thumb : null;
}

/** «из N трека/треков» — родительный падеж после «из». */
function ofTracks(n) {
  return n % 10 === 1 && n % 100 !== 11 ? 'трека' : 'треков';
}

/**
 * Ответ link/inspect для формы «Новая песня»:
 * → {kind: 'track', track} | {kind: 'list', count, text} | {kind: 'empty', text}
 * Один трек (в том числе альбом из одного) — берётся; больше — подсказка про «Импорт → Ссылка».
 */
export function linkOutcome(info) {
  const tracks = Array.isArray(info?.tracks) ? info.tracks : [];
  if (!tracks.length) return { kind: 'empty', text: NO_TRACKS };
  if (tracks.length === 1) return { kind: 'track', track: tracks[0] };
  const n = tracks.length;
  return { kind: 'list', count: n, text: `Это список из ${n} ${ofTracks(n)} — откройте Импорт → Ссылка` };
}

export const YM_REMOVE_CONFIRM = 'Поле токена пустое. Удалить сохранённый токен Яндекс Музыки? Генерация по ссылкам music.yandex.ru перестанет работать.';
export const YM_KEPT = 'Токен сохранён и не изменился. Чтобы заменить — впишите новый токен в поле; чтобы удалить — «Сохранить» с пустым полем и подтверждение.';
export const YM_EMPTY = 'Впишите токен в поле — сохранять нечего';

/**
 * «Сохранить» в карточке «Яндекс Музыка»: 'save' — вписан токен; 'confirm-remove' — поле пустое,
 * а токен сохранён (удалять только после подтверждения, иначе — подсказка YM_KEPT);
 * 'empty' — поле пустое и токена нет (подсказка YM_EMPTY, запроса нет).
 */
export function yandexSaveAction(input, hasToken) {
  if (String(input ?? '').trim()) return 'save';
  return hasToken ? 'confirm-remove' : 'empty';
}
