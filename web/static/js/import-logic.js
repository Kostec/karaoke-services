// Импорт готовых песен: чистая логика без DOM (выбор звука, предупреждения, поля формы).
// Тексты совпадают с web/app/api_import.py.

export const NEED_AUDIO = 'Нужен звук: загрузите mp3 или вставьте ссылку на YouTube';
export const WARN_SYNC = 'Ноты сделаны под конкретную запись — с другой версией слова могут разъехаться';
export const EXPIRED = 'Загрузка устарела, загрузите заново';
export const DUP_TEXT = 'Уже есть в папке результата';

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
  const found = (song.youtube || []).find((u) => u && u.trim());
  return found ? { kind: 'youtube', url: found.trim() } : { kind: 'none' };
}

/** Предупреждения карточки: про звук считаются заново по выбору, прочие от сервера — как есть. */
export function importWarnings(song, audio) {
  const out = [];
  if (audio.kind === 'none') out.push(NEED_AUDIO);
  else if (audio.kind !== 'archive') out.push(WARN_SYNC);
  for (const w of song.warnings || []) {
    if (w !== NEED_AUDIO && w !== WARN_SYNC && !out.includes(w)) out.push(w);
  }
  return out;
}

/** Начальное состояние карточки: дубли не отмечены (G01.1, R06i.1); минусовка выключена,
 * если у песни в архиве уже есть свой [Instrumental] — иначе задание его перезапишет (G05). */
export function initialCardState(song) {
  return {
    selected: !song.existing_song_id,
    artist: song.artist || '',
    title: song.title || '',
    youtube: (song.youtube || [])[0] || '',
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
  if (e?.status === 410) return { kind: 'expired', text: EXPIRED };
  return { kind: 'error', text: (e && (e.detail || e.message)) || 'Ошибка', field: data.field || null };
}
