// Редактор строк готовой песни (G05.1–G05.4, истории 49–52): слоги-ноты с редактируемым текстом,
// склейка/разбивка строк, удаление нот, ▶ отрывка строки, сохранение PUT /notes.
// Дуэты и #RELATIVE — только чтение (причину присылает сервер).

import { api, errorText } from '../api.js';
import { h, clear, songName } from '../ui.js';
import { openShell, fmtTime } from './shell.js';
import {
  lineRange, lineText, canPlay, setSyllable, mergeWithNext, splitBefore, deleteNote, toPayload, isDirty,
} from './lines.js';

export async function openLinesEditor(song, { reload } = {}) {
  let data = null; // ответ GET /notes
  let original = [];
  let lines = [];
  let sel = null; // {li, ni} — выбранный слог
  let busy = false;

  const list = h('ol', { class: 'ed-lines' });
  const help = h('p', { class: 'small muted ed-help' },
    'Пробел в начале слога — граница слова. Выберите слог, чтобы разбить строку перед ним или удалить ноту. '
    + 'Тайминги и высоты нот не меняются.');
  const saveBtn = h('button', { type: 'button', class: 'primary', disabled: true }, 'Сохранить');
  const state = h('span', { class: 'small muted' });
  const audio = h('audio', { preload: 'none', src: song.audio ? api.audioUrl(song.song_id) : null });

  const shell = openShell({
    title: 'Слова песни',
    subtitle: songName(song.artist, song.title),
    isDirty: () => !!data?.editable && isDirty(lines, original),
  });
  shell.body.append(help, list, audio);
  shell.footer.append(state, saveBtn);
  shell.dlg.addEventListener('editor-close', () => stopPlay());
  shell.message('Загрузка…', 'warn');

  // ------------------------------------------------------------ проигрывание строки

  let stopAt = null, raf = 0, playingLi = null;
  function stopPlay() {
    cancelAnimationFrame(raf);
    stopAt = null;
    if (!audio.paused) audio.pause();
    if (playingLi !== null) list.children[playingLi]?.classList.remove('playing');
    playingLi = null;
    for (const b of list.querySelectorAll('.ed-play')) b.textContent = '▶';
  }
  function tick() {
    if (stopAt === null) return;
    if (audio.currentTime >= stopAt || audio.ended) { stopPlay(); return; }
    raf = requestAnimationFrame(tick);
  }
  async function play(li, btn) {
    if (playingLi === li) { stopPlay(); return; }
    stopPlay();
    const { start, end } = lineRange(lines[li], data.gap, data.bpm);
    try {
      audio.currentTime = start / 1000;
      await audio.play();
    } catch (e) {
      shell.message(`Не удалось проиграть: ${e.message || 'аудио недоступно'}`, 'err');
      return;
    }
    stopAt = end / 1000;
    playingLi = li;
    list.children[li]?.classList.add('playing');
    btn.textContent = '■';
    raf = requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------ отрисовка

  function updateState() {
    const dirty = data?.editable && isDirty(lines, original);
    saveBtn.disabled = busy || !dirty;
    state.textContent = data?.editable ? (dirty ? 'Есть несохранённые правки' : 'Правок нет') : '';
  }

  function apply(fn) {
    try {
      lines = fn(lines);
      shell.message('');
    } catch (e) {
      shell.message(e.message, 'err');
      return;
    }
    sel = null;
    render();
  }

  function syllable(li, ni, note, preview, tools) {
    const ro = !data.editable;
    const inp = h('input', {
      type: 'text', class: `ed-syl${note.type === '*' ? ' golden' : ''}${note.type === 'F' || note.type === 'R' || note.type === 'G' ? ' free' : ''}`,
      value: note.text, readonly: ro, spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off',
      'aria-label': `Строка ${li + 1}, слог ${ni + 1}`,
    });
    inp.style.width = `${Math.max(2, note.text.length + 1)}ch`;
    inp.addEventListener('focus', () => {
      sel = { li, ni };
      for (const el of list.querySelectorAll('.ed-syl.sel')) el.classList.remove('sel');
      inp.classList.add('sel');
      for (const b of list.querySelectorAll('.ed-tools [data-act=split], .ed-tools [data-act=del]')) b.disabled = true;
      tools.querySelector('[data-act=split]').disabled = ro || ni === 0;
      tools.querySelector('[data-act=del]').disabled = ro;
    });
    inp.addEventListener('input', () => {
      lines = setSyllable(lines, li, ni, inp.value);
      inp.style.width = `${Math.max(2, inp.value.length + 1)}ch`;
      preview.textContent = lineText(lines[li]) || '—';
      updateState();
    });
    return inp;
  }

  function row(line, li) {
    const ro = !data.editable;
    const { start, end } = lineRange(line, data.gap, data.bpm);
    const preview = h('div', { class: 'ed-preview' }, lineText(line) || '—');
    const playable = canPlay(song, data);
    const timed = Number(data.bpm) > 0;
    const playBtn = h('button', {
      type: 'button', class: 'ed-play', disabled: playable !== true,
      title: playable === true ? `Проиграть ${fmtTime(start)}–${fmtTime(end)}` : playable,
      'aria-label': `Проиграть строку ${li + 1}`,
    }, '▶');
    playBtn.addEventListener('click', () => play(li, playBtn));
    const btn = (act, label, title) => h('button', { type: 'button', class: 'small-btn', dataset: { act }, disabled: true, title }, label);
    const tools = h('div', { class: 'ed-tools' },
      btn('split', 'Разбить перед слогом', 'Начать новую строку с выбранного слога'),
      btn('del', 'Удалить ноту', 'Удалить выбранный слог вместе с нотой'),
      h('button', { type: 'button', class: 'small-btn', dataset: { act: 'merge' }, disabled: ro || li === lines.length - 1,
        title: 'Соединить эту строку со следующей' }, 'Склеить со следующей'));
    tools.addEventListener('click', (e) => {
      const act = e.target.closest('button')?.dataset.act;
      if (!act) return;
      if (act === 'merge') apply((ls) => mergeWithNext(ls, li));
      else if (sel && sel.li === li) {
        if (act === 'split') apply((ls) => splitBefore(ls, li, sel.ni));
        if (act === 'del') apply((ls) => deleteNote(ls, li, sel.ni));
      }
    });
    const syls = h('div', { class: 'ed-syls' }, line.notes.map((n, ni) => syllable(li, ni, n, preview, tools)));
    return h('li', { class: 'ed-line' },
      h('div', { class: 'ed-line-head' }, playBtn,
        h('span', { class: 'ed-num' }, `${li + 1}`),
        h('span', { class: 'small muted' }, timed ? fmtTime(start) : ''),
        preview),
      syls,
      ro ? null : tools);
  }

  function render() {
    stopPlay();
    clear(list).append(...lines.map(row));
    updateState();
  }

  // ------------------------------------------------------------ загрузка и сохранение

  async function load() {
    data = await api.notes(song.song_id);
    original = data.lines.map((l) => ({ break_beat: l.break_beat, notes: l.notes }));
    lines = original;
    if (!data.editable) {
      shell.message(data.reason || 'Эту песню можно только просмотреть', 'warn');
      saveBtn.hidden = true;
      help.hidden = true;
    } else if (!(Number(data.bpm) > 0)) {
      shell.message('В песне нет #BPM — время строк неизвестно, ▶ недоступна', 'warn');
    } else {
      shell.message('');
    }
    render();
  }

  saveBtn.addEventListener('click', async () => {
    busy = true;
    updateState();
    try {
      await api.saveNotes(song.song_id, toPayload(lines));
      await load();
      shell.message('Сохранено. Прежняя версия .txt — в корзине.', 'ok');
      reload?.();
    } catch (e) {
      shell.message(errorText(e, 'Не удалось сохранить'), 'err');
    } finally {
      busy = false;
      updateState();
    }
  });

  try {
    await load();
  } catch (e) {
    shell.message(`Не удалось открыть песню: ${errorText(e)}`, 'err');
  }
}
