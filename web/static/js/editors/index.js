// Редакторы карточки песни (таск 07): регистрируются в extensions.js, подключаются одной строкой в app.js.

import { registerSongEditor } from '../extensions.js';
import { openLyricsEditor, lyricsEnabled } from './lyrics-editor.js';
import { openNotesEditor } from './notes-editor.js';

registerSongEditor('lyrics', {
  label: 'Править текст',
  enabled: lyricsEnabled,
  open: (song, opts) => openLyricsEditor(song, opts),
});

registerSongEditor('notes', {
  label: 'Редактор нот',
  open: (song, opts) => openNotesEditor(song, opts),
});
