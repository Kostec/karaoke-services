// Обложка и фон песни — чистая логика диалогов (artwork.js) без DOM: проверка файла и ссылки,
// подписи вариантов поиска, поля формы POST /api/jobs/artwork.

export const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp'];
export const IMAGE_ACCEPT = 'image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp';
export const NOT_IMAGE = 'Это не картинка (нужны jpg, png или webp)';
export const NOTHING_FOUND = 'Обложек не нашлось — уточните название или загрузите свой файл';
export const SOURCE_LABELS = { itunes: 'iTunes', deezer: 'Deezer', musicbrainz: 'MusicBrainz' };

const MB = 1024 * 1024;

/** Ошибка выбранного файла картинки или null (тексты — как у сервера). */
export function imageError(file, maxMb) {
  if (!file) return 'Выберите файл';
  const name = String(file.name || '').toLowerCase();
  const type = String(file.type || '').toLowerCase();
  const okExt = IMAGE_EXTS.some((e) => name.endsWith(e));
  const okType = ['image/jpeg', 'image/png', 'image/webp'].includes(type);
  if (!okExt && !okType) return NOT_IMAGE;
  if (maxMb && file.size > maxMb * MB) return `Файл больше ${maxMb} МБ`;
  return null;
}

/** Ошибка ссылки на картинку или null; домашнюю сеть и «не картинку» проверяет сервер. */
export function urlError(raw) {
  const url = String(raw ?? '').trim();
  if (!url) return 'Вставьте ссылку на картинку';
  let u;
  try { u = new URL(url); } catch { return 'Нужна ссылка http(s) на картинку'; }
  if (!['http:', 'https:'].includes(u.protocol) || !u.hostname) return 'Нужна ссылка http(s) на картинку';
  return null;
}

/** Размер варианта «1000×1000» или пусто. */
export function hitSize(hit) {
  return hit?.width && hit?.height ? `${hit.width}×${hit.height}` : '';
}

/** Подпись варианта: источник · альбом (или «исполнитель — название») · размер. */
export function hitLabel(hit) {
  const what = hit.album || [hit.artist, hit.title].filter(Boolean).join(' — ');
  return [SOURCE_LABELS[hit.source] || hit.source, what, hitSize(hit)].filter(Boolean).join(' · ');
}

/** Строка под сеткой: сколько нашлось и какие сервисы не ответили. */
export function searchNote({ items = [], failed = [] } = {}) {
  if (!items.length) return NOTHING_FOUND;
  let text = `Найдено вариантов: ${items.length}`;
  if (failed.length) {
    const names = failed.map((s) => SOURCE_LABELS[s] || s).join(', ');
    text += ` · ${names} ${failed.length > 1 ? 'не ответили' : 'не ответил'}`;
  }
  return text;
}

/** Поля формы задания: mode — search (выбранный вариант), url, file или remove. */
export function artworkFields({ kind, mode, file = null, url = '', hit = null }) {
  if (mode === 'remove') return { kind, remove: 'true' };
  if (mode === 'file') return { kind, image: file };
  if (mode === 'search') return { kind, url: String(hit?.url || '').trim() };
  return { kind, url: String(url || '').trim() };
}

/** Ссылка — альбом или плейлист (linkOutcome → kind 'list'): «Новая песня» ведёт в «Импорт». */
export function isListLink(outcome) {
  return outcome?.kind === 'list';
}

/** Ключ sessionStorage: ссылка, которую «Импорт → Ссылка» разберёт при открытии. */
export const IMPORT_URL_KEY = 'import.url';
