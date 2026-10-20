// Редактор исходного текста (G05): разбор строк для номеров/подсветки и поля задания перегенерации.

/** Параметры генерации, которые форма передаёт в params (как в new-song.js). */
export const PARAM_KEYS = ['whisper_model', 'language', 'compute_type', 'batch_size', 'align_model',
  'vad_onset', 'vad_offset', 'demucs_model', 'keep_debug'];

/** Строка-метка вида «[Припев]» целиком — UltraSinger её удалит. */
export function isMarker(line) {
  return /^\s*\[[^\]]*\]\s*$/.test(line);
}

/** Строки текста с номерами и признаком метки; total — все строки, sung — непустые без меток. */
export function analyzeLyrics(text) {
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n')
    .map((t, i) => ({ n: i + 1, text: t, marker: isMarker(t) }));
  return {
    lines,
    total: lines.length,
    markers: lines.filter((l) => l.marker).length,
    sung: lines.filter((l) => !l.marker && l.text.trim()).length,
  };
}

/**
 * Поля multipart для POST /api/jobs/generate («Сохранить и перегенерировать»):
 * текст из редактора, параметры прошлой генерации песни поверх умолчаний формы, replace.
 */
export function regenFields(song, text, defaults = {}) {
  const src = { ...(defaults || {}), ...(song.params || {}) };
  const params = {};
  for (const k of PARAM_KEYS) if (src[k] !== undefined) params[k] = src[k];
  return {
    artist: song.artist || '',
    title: song.title || '',
    lyrics: String(text ?? '').replace(/\r\n?/g, '\n'),
    params: JSON.stringify(params),
    song_id: song.song_id,
    replace: 'true',
  };
}
