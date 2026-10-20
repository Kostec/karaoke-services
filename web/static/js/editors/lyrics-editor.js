// Редактор исходного текста (G05, история 48): моноширинный текст с номерами строк,
// подсветка строк-меток «[...]» («будет удалена»), «Сохранить и перегенерировать».

import { api, getDefaults } from '../api.js';
import { h, clear, toast, songName } from '../ui.js';
import { openShell } from './shell.js';
import { analyzeLyrics, regenFields } from './lyrics-text.js';

export function lyricsEnabled(song) {
  return song.own || song.audio ? true : 'У песни нет аудиофайла — перегенерация невозможна';
}

export async function openLyricsEditor(song) {
  let original = '';
  const ta = h('textarea', { class: 'ed-text', wrap: 'off', spellcheck: 'false', autocapitalize: 'off', 'aria-label': 'Текст песни', disabled: true });
  const gutter = h('div', { class: 'ed-gutter', 'aria-hidden': 'true' });
  const backdrop = h('pre', { class: 'ed-backdrop', 'aria-hidden': 'true' });
  const counter = h('div', { class: 'small muted ed-counter', 'aria-live': 'polite' });
  const source = h('div', { class: 'small muted' });
  const saveBtn = h('button', { type: 'button', class: 'primary', disabled: true }, 'Сохранить и перегенерировать');
  const hint = h('div', { class: 'small muted' });

  const shell = openShell({
    title: 'Текст песни',
    subtitle: songName(song.artist, song.title),
    isDirty: () => !ta.disabled && ta.value !== original,
  });
  shell.body.append(source,
    h('div', { class: 'ed-textwrap' }, gutter, h('div', { class: 'ed-textarea' }, backdrop, ta)),
    counter);
  shell.footer.append(hint, saveBtn);
  shell.message('Загрузка текста…', 'warn');

  function render() {
    const r = analyzeLyrics(ta.value);
    clear(gutter).append(...r.lines.map((l) => h('div', { class: l.marker ? 'marker' : null }, String(l.n))));
    clear(backdrop).append(...r.lines.map((l) => (l.marker
      ? h('span', { class: 'marker', 'data-note': '  ← будет удалена' }, l.text)
      : h('span', {}, l.text || ' '))));
    counter.textContent = `Строк: ${r.total} · с текстом: ${r.sung}`
      + (r.markers ? ` · меток: ${r.markers} (будут удалены)` : '');
    const foreignEmpty = !song.own && !ta.value.trim();
    saveBtn.disabled = ta.disabled || foreignEmpty;
    hint.textContent = foreignEmpty ? 'Для чужой песни нужен текст' : '';
    syncScroll();
  }
  function syncScroll() {
    backdrop.scrollTop = ta.scrollTop;
    backdrop.scrollLeft = ta.scrollLeft;
    gutter.scrollTop = ta.scrollTop;
  }
  ta.addEventListener('input', render);
  ta.addEventListener('scroll', syncScroll);

  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    shell.message('');
    let defaults = {};
    try { defaults = (await getDefaults()).defaults || {}; } catch { /* сервер подставит свои */ }
    const fd = new FormData();
    for (const [k, v] of Object.entries(regenFields(song, ta.value, defaults))) fd.append(k, v);
    try {
      await api.generate(fd);
      original = ta.value;
      await shell.close(true);
      toast(`«${songName(song.artist, song.title)}» поставлена на перегенерацию`);
      location.hash = '#queue';
    } catch (e) {
      shell.message(e.detail || 'Не удалось поставить задание', 'err');
      render();
    }
  });

  render();
  try {
    const res = await api.lyrics(song.song_id);
    original = (res.text || '').replace(/\r\n?/g, '\n');
    ta.value = original;
    ta.disabled = false;
    source.textContent = res.source === 'own'
      ? 'Исходный текст, с которым песня генерировалась.'
      : 'Текст собран из слов готовой песни (.txt). После правки песня будет сгенерирована заново.';
    shell.message('');
  } catch (e) {
    shell.message(`Не удалось загрузить текст: ${e.detail}`, 'err');
  }
  render();
  ta.focus();
}
