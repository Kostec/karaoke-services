// Импорт готовых песен: чистая логика без DOM (выбор звука, предупреждения, поля формы).
// Тексты сервера фронт показывает из ответа (warnings, detail); свои — только для того, чего
// сервер не знает. NEED_AUDIO и WARN_SYNC совпадают с web/app/api_import.py: блокировка кнопки
// до постановки и предупреждение о своём звуке; EXPIRED — запасной, если в 410 нет detail.

export const NEED_AUDIO = 'Нужен звук: загрузите mp3 или вставьте ссылку на YouTube';
export const WARN_SYNC = 'Ноты сделаны под конкретную запись — с другой версией слова могут разъехаться';
export const EXPIRED = 'Загрузка устарела, загрузите заново';
export const DUP_TEXT = 'Уже есть в папке результата';

/** Первая непустая ссылка песни после trim (или ''). */
function songLink(song) {
  const found = (song.youtube || []).find((u) => u && u.trim());
  return found ? found.trim() : '';
}

/**
 * Откуда возьмётся звук (R07i): свой mp3 → аудио из архива → своя ссылка YouTube → ссылка из песни.
 * song — элемент ответа inspect; form — {file?: File, youtube?: string}.
 * → {kind: 'upload'|'archive', name} | {kind: 'youtube', url} | {kind: 'none'}
 */
export function pickAudioSource(song, form = {}) {
  if (form.file) return { kind: 'upload', name: form.file.name };
  if (song.audio) return { kind: 'archive', name: song.audio };
  const own = (form.youtube || '').trim();
  if (own) return { kind: 'youtube', url: own };
  const found = songLink(song);
  return found ? { kind: 'youtube', url: found } : { kind: 'none' };
}

/**
 * Предупреждения карточки. Звук песни как в разборе (архив, её ссылка, звука нет) — warnings
 * сервера как есть. Свой mp3 или своя ссылка — этого сервер не видел, и его warnings (они про звук
 * песни, api_import._warnings) устарели: вместо них — своё WARN_SYNC.
 */
export function importWarnings(song, audio) {
  const own = audio.kind === 'upload' || (audio.kind === 'youtube' && audio.url !== songLink(song));
  return own ? [WARN_SYNC] : [...(song.warnings || [])];
}

/** Начальное состояние карточки: дубли не отмечены (G01.1, R06i.1); минусовка выключена,
 * если у песни в архиве уже есть свой [Instrumental] — иначе задание его перезапишет (G05). */
export function initialCardState(song) {
  return {
    selected: !song.existing_song_id,
    artist: song.artist || '',
    title: song.title || '',
    youtube: songLink(song), // то же правило, что у pickAudioSource
    instrumental: !song.has_instrumental,
    replace: false,
    existing: song.existing_song_id || null,
  };
}

/** Поля POST /api/jobs/import для карточки (state: initialCardState + file?). */
export function importFields(token, song, state) {
  const audio = pickAudioSource(song, state);
  const out = { token, index: song.index, artist: (state.artist || '').trim(), title: (state.title || '').trim() };
  if (audio.kind === 'upload') out.audio = state.file;
  if (audio.kind === 'youtube') out.youtube_url = audio.url;
  out.instrumental = !!state.instrumental;
  out.replace = !!state.replace;
  return out;
}

/** Почему «Импортировать выбранные» недоступна; null — можно. items: [{song, state}]. */
export function importBlocker(items) {
  const chosen = items.filter((i) => i.state.selected);
  if (!chosen.length) return 'Отметьте песни для импорта';
  if (chosen.some((i) => !i.state.artist?.trim() || !i.state.title?.trim())) return 'Укажите исполнителя и название';
  if (chosen.some((i) => pickAudioSource(i.song, i.state).kind === 'none')) return NEED_AUDIO;
  return null;
}

/** Ошибка постановки → что показать на карточке. */
export function importOutcome(e) {
  const data = (e && e.data) || {};
  if (e?.status === 409 && data.song_id) return { kind: 'duplicate', songId: data.song_id, text: DUP_TEXT };
  if (e?.status === 410) return { kind: 'expired', text: (e && e.detail) || EXPIRED };
  return { kind: 'error', text: (e && (e.detail || e.message)) || 'Ошибка', field: data.field || null };
}

/** Текст закрытого пака после 410: сколько песен из него уже поставлено в очередь. */
export function expiredMessage(text, queued) {
  const base = String(text || EXPIRED).trim();
  if (!queued) return base;
  return `${base.replace(/[.!]+$/, '')}. Уже поставлено в очередь: ${queued} — их загружать заново не нужно`;
}
