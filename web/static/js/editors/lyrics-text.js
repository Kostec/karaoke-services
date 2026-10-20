// Редактор исходного текста (G05): разбор строк для номеров/подсветки и поля задания перегенерации.

import { pickParams } from '../api.js';

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
 * Поля задания generate («Сохранить и перегенерировать») для api.generateForm:
 * текст из редактора, параметры прошлой генерации песни поверх умолчаний формы, replace.
 */
export function regenFields(song, text, defaults = {}) {
  return {
    artist: song.artist || '',
    title: song.title || '',
    lyrics: String(text ?? '').replace(/\r\n?/g, '\n'),
    params: pickParams({ ...(defaults || {}), ...(song.params || {}) }),
    song_id: song.song_id,
    replace: true,
  };
}
