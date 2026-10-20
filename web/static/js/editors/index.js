// Редакторы карточки песни (таск 07): регистрируются в extensions.js, подключаются одной строкой в app.js.

import { registerSongEditor } from '../extensions.js';
import { openLyricsEditor, lyricsEnabled } from './lyrics-editor.js';
import { openNotesEditor, addNotesEditorPlugin } from './notes-editor.js';
import { textPanelPlugin } from './notes-text-panel.js';
import { toolsPlugin } from './notes-tools.js';

registerSongEditor('lyrics', {
  label: 'Править текст',
  enabled: lyricsEnabled,
  open: (song, opts) => openLyricsEditor(song, opts),
});

registerSongEditor('notes', {
  label: 'Редактор нот',
  open: (song, opts) => openNotesEditor(song, opts),
});

// расширения редактора нот (таск 04): панель «Текст», перенос текста, отстукивание, справка
addNotesEditorPlugin(textPanelPlugin);
addNotesEditorPlugin(toolsPlugin);
