// Точки расширения карточки песни (редакторы — таск 07).
//
// Модуль редактора регистрирует себя:
//   import { registerSongEditor } from '../extensions.js';
//   registerSongEditor('lyrics', { label: 'Редактировать текст', open(song, { reload }) { … } });
//   registerSongEditor('notes',  { label: 'Редактировать слова', open(song, { reload }) { … } });
// и подключается одной строкой импорта в app.js (см. комментарий «Редакторы»).
// song — элемент из GET /api/songs (song_id, artist, title, own, …);
// reload() — перечитать список песен после сохранения.
// enabled(song) (необязательно) → true | строка-причина, почему кнопка неактивна.

export const EDITOR_SLOTS = ['lyrics', 'notes'];

const editors = new Map();
const listeners = new Set();

export function registerSongEditor(kind, editor) {
  if (!EDITOR_SLOTS.includes(kind)) throw new Error(`Неизвестный редактор: ${kind}`);
  editors.set(kind, editor);
  listeners.forEach((fn) => fn());
}

export function songEditors() {
  return EDITOR_SLOTS.filter((k) => editors.has(k)).map((k) => ({ kind: k, ...editors.get(k) }));
}

export function onEditorsChanged(fn) {
  listeners.add(fn);
}
