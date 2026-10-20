// Раздел «Новая песня» (и перегенерация песни из списка: #new?song=<song_id>).

import { api } from './api.js';
import { h, clear, toast, debounce, songName } from './ui.js';

const PARAM_KEYS = ['whisper_model', 'language', 'compute_type', 'batch_size', 'align_model',
  'vad_onset', 'vad_offset', 'demucs_model', 'keep_debug'];

let root, form, f = {}, defaults = null, defaultsError = null;
let regen = null; // карточка песни при перегенерации
let replace = false; // пользователь выбрал «Заменить»
let dupId = null; // song_id совпавшей песни
let submitting = false;
let alignTouched = false;
let existsSeq = 0;

export function mount(section) {
  root = section;
}

export async function show(params) {
  if (!form) await build();
  const songId = params.get('song');
  if (songId && (!regen || regen.song_id !== songId)) {
    await loadRegen(songId);
  } else if (!songId && regen) {
    resetForm();
  }
}

// ---------------------------------------------------------------- построение формы

function field(label, input, hint) {
  return h('label', { class: 'field' }, h('span', {}, label, hint ? h('span', { class: 'hint' }, ` (${hint})`) : null), input);
}

function select(name, options) {
  return h('select', { name }, options.map(([v, t]) => h('option', { value: v }, t)));
}

async function build() {
  try {
    defaults = await api.defaults();
  } catch (e) {
    defaultsError = e.detail;
  }
  const d = defaults || { whisper_models: [], compute_types: [], demucs_models: [], languages: [], defaults: {}, align_models: {} };

  f.regenBanner = h('div', { class: 'banner warn', hidden: true });
  f.artist = h('input', { type: 'text', name: 'artist', autocomplete: 'off', required: true, maxlength: '200' });
  f.title = h('input', { type: 'text', name: 'title', autocomplete: 'off', required: true, maxlength: '200' });
  f.artistErr = h('div', { class: 'field-error', hidden: true }, 'Укажите исполнителя');
  f.titleErr = h('div', { class: 'field-error', hidden: true }, 'Укажите название');

  f.dupText = h('p', { style: 'margin:0 0 4px' });
  f.dupHint = h('div', { class: 'small' });
  f.dup = h('div', { class: 'banner warn', hidden: true, role: 'alert' }, f.dupText, f.dupHint,
    h('div', { class: 'actions' },
      h('button', { type: 'button', class: 'primary', onclick: () => chooseReplace(true) }, 'Заменить'),
      h('button', { type: 'button', onclick: () => chooseReplace(false) }, 'Отмена')));

  f.audio = h('input', { type: 'file', name: 'audio', accept: '.mp3,audio/mpeg' });
  f.audioHint = h('div', { class: 'small muted' });
  f.audioErr = h('div', { class: 'field-error', hidden: true });

  f.lyrics = h('textarea', { name: 'lyrics', rows: '10', placeholder: 'Вставьте текст песни или выберите файл .txt / .lrc' });
  f.lyricsFile = h('input', { type: 'file', accept: '.txt,.lrc,text/plain', 'aria-label': 'Файл текста' });
  f.lyricsWarn = h('div', { class: 'banner warn small' }, 'Без текста слова будут распознаны автоматически — качество ниже');
  f.lyricsErr = h('div', { class: 'field-error', hidden: true });

  f.cover = h('input', { type: 'file', name: 'cover', accept: '.jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp' });
  f.coverErr = h('div', { class: 'field-error', hidden: true });

  f.whisper_model = select('whisper_model', d.whisper_models.map((m) => [m, m]));
  f.language = select('language', d.languages.map((l) => [l.code, `${l.name} (${l.code})`]));
  f.compute_type = select('compute_type', d.compute_types.map((m) => [m, m]));
  f.batch_size = h('input', { type: 'number', name: 'batch_size', min: '1', max: '64', step: '1', inputmode: 'numeric' });
  f.align_model = h('input', { type: 'text', name: 'align_model', autocomplete: 'off', placeholder: 'пусто — по умолчанию UltraSinger' });
  f.vad_onset = h('input', { type: 'number', name: 'vad_onset', min: '0', max: '1', step: '0.01', inputmode: 'decimal', placeholder: 'по умолчанию' });
  f.vad_offset = h('input', { type: 'number', name: 'vad_offset', min: '0', max: '1', step: '0.01', inputmode: 'decimal', placeholder: 'по умолчанию' });
  f.demucs_model = select('demucs_model', d.demucs_models.map((m) => [m, m]));
  f.keep_debug = h('input', { type: 'checkbox', name: 'keep_debug' });

  f.error = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  f.submit = h('button', { type: 'submit', class: 'primary' }, 'Поставить в очередь');
  f.cancelRegen = h('a', { class: 'btn', href: '#songs', hidden: true }, 'К списку песен');
  f.submitHint = h('div', { class: 'small muted' });

  form = h('form', { class: 'card', novalidate: true },
    f.regenBanner,
    h('div', { class: 'row2' },
      h('div', {}, field('Исполнитель', f.artist), f.artistErr),
      h('div', {}, field('Название', f.title), f.titleErr)),
    f.dup,
    field('Аудио mp3', f.audio, `до ${d.max_upload_mb || '?'} МБ`), f.audioHint, f.audioErr,
    h('div', { class: 'field' },
      h('span', {}, 'Текст песни', h('span', { class: 'hint' }, ' (можно оставить пустым)')),
      f.lyrics,
      h('div', { class: 'inline-file' }, h('span', { class: 'small muted' }, 'или файл:'), f.lyricsFile),
      f.lyricsErr),
    f.lyricsWarn,
    field('Обложка', f.cover, `jpg, png или webp до ${d.max_cover_mb || 10} МБ, необязательно`), f.coverErr,
    h('div', { class: 'row2' }, field('Модель Whisper', f.whisper_model), field('Язык песни', f.language)),
    h('details', { class: 'more' }, h('summary', {}, 'Дополнительно'),
      h('div', { class: 'row2' },
        field('Тип вычислений', f.compute_type, 'float16 GTX 1080 не поддерживает'),
        field('Размер пакета (batch size)', f.batch_size, 'меньше — меньше видеопамяти'),
        field('Модель выравнивания', f.align_model),
        field('Модель Demucs', f.demucs_model),
        field('Порог начала речи (VAD onset)', f.vad_onset, 'от 0 до 1'),
        field('Порог конца речи (VAD offset)', f.vad_offset, 'от 0 до 1')),
      h('label', { class: 'check' }, f.keep_debug, 'Сохранить отладку выравнивания')),
    f.error,
    h('div', { class: 'actions' }, f.submit, f.cancelRegen),
    f.submitHint);

  form.addEventListener('submit', onSubmit);
  const onName = debounce(checkExists, 450);
  for (const el of [f.artist, f.title]) {
    el.addEventListener('input', () => {
      el.classList.remove('invalid');
      (el === f.artist ? f.artistErr : f.titleErr).hidden = true;
      replace = false;
      onName();
    });
  }
  f.lyrics.addEventListener('input', updateLyricsState);
  f.lyricsFile.addEventListener('change', onLyricsFile);
  f.audio.addEventListener('change', () => checkAudio());
  f.cover.addEventListener('change', () => checkCover());
  f.language.addEventListener('change', () => {
    if (!alignTouched) f.align_model.value = (defaults?.align_models || {})[f.language.value] || '';
  });
  f.align_model.addEventListener('input', () => { alignTouched = true; });

  clear(root).append(h('div', { class: 'view-head' }, h('h2', { id: 'new-title' }, 'Новая песня')));
  if (defaultsError) root.append(h('div', { class: 'banner err' }, `Не удалось загрузить настройки формы: ${defaultsError}`));
  root.append(form);
  setParams(d.defaults || {});
  updateLyricsState();
}

function setParams(p) {
  for (const k of PARAM_KEYS) {
    const el = f[k];
    const v = p[k];
    if (el.type === 'checkbox') el.checked = !!v;
    else if (v !== undefined) el.value = v === null ? '' : String(v);
  }
  alignTouched = false;
}

function resetForm() {
  form.reset();
  regen = null;
  replace = false;
  dupId = null;
  f.dup.hidden = true;
  f.error.hidden = true;
  f.regenBanner.hidden = true;
  f.cancelRegen.hidden = true;
  f.audioHint.textContent = '';
  for (const e of [f.audioErr, f.coverErr, f.lyricsErr, f.artistErr, f.titleErr]) e.hidden = true;
  for (const e of [f.artist, f.title]) e.classList.remove('invalid');
  document.getElementById('new-title').textContent = 'Новая песня';
  setParams(defaults?.defaults || {});
  updateLyricsState();
}

// ---------------------------------------------------------------- перегенерация

async function loadRegen(songId) {
  resetForm();
  f.regenBanner.textContent = 'Загрузка песни…';
  f.regenBanner.hidden = false;
  f.submit.disabled = true;
  try {
    const song = await api.song(songId);
    regen = song;
    document.getElementById('new-title').textContent = 'Перегенерация';
    f.artist.value = song.artist || '';
    f.title.value = song.title || '';
    if (song.params) setParams({ ...(defaults?.defaults || {}), ...song.params });
    let text = song.lyrics;
    if (text == null) {
      try { text = (await api.lyrics(songId)).text; } catch (e) { toast(`Текст не загрузился: ${e.detail}`, 'err'); }
    }
    f.lyrics.value = text || '';
    f.regenBanner.textContent = `Перегенерация «${songName(song.artist, song.title)}». После успеха старая версия уйдёт в корзину.`;
    f.audioHint.textContent = song.own
      ? 'Можно не выбирать: возьмётся mp3 из исходников песни.'
      : 'Можно не выбирать: возьмётся аудио из папки песни.';
    f.cancelRegen.hidden = false;
  } catch (e) {
    regen = null;
    f.regenBanner.textContent = `Не удалось открыть песню: ${e.detail}`;
    f.regenBanner.className = 'banner err';
    return;
  } finally {
    f.submit.disabled = false;
    updateLyricsState();
  }
  f.regenBanner.className = 'banner warn';
}

// ---------------------------------------------------------------- проверки

function updateLyricsState() {
  const empty = !f.lyrics.value.trim();
  f.lyricsWarn.hidden = !empty;
  const foreignEmpty = regen && !regen.own && empty;
  f.submitHint.textContent = foreignEmpty ? 'Для чужой песни нужен текст' : '';
  updateSubmit();
}

function updateSubmit() {
  const foreignEmpty = regen && !regen.own && !f.lyrics.value.trim();
  const dupBlock = dupId && !replace;
  f.submit.disabled = submitting || !!foreignEmpty || !!dupBlock;
  if (dupBlock && !foreignEmpty) f.submitHint.textContent = 'Выберите «Заменить» или измените исполнителя и название';
  else if (!foreignEmpty) f.submitHint.textContent = '';
}

async function checkExists() {
  const artist = f.artist.value.trim(), title = f.title.value.trim();
  const seq = ++existsSeq;
  if (!artist || !title) { showDup(null); return; }
  try {
    const r = await api.exists(artist, title);
    if (seq !== existsSeq) return;
    showDup(r.exists && (!regen || r.song_id !== regen.song_id) ? r.song_id : null);
  } catch {
    // проверку повторит сервер при отправке
  }
}

function showDup(songId) {
  dupId = songId;
  if (!songId) replace = false;
  f.dup.hidden = !songId;
  f.dupText.textContent = 'Такая песня уже есть';
  f.dupHint.textContent = replace
    ? 'Старая версия уйдёт в корзину после успешной генерации.'
    : 'Заменить её новой версией? Старая уйдёт в корзину после успешной генерации.';
  updateSubmit();
}

function chooseReplace(yes) {
  replace = yes;
  if (yes) {
    showDup(dupId);
  } else {
    f.dup.hidden = true;
    updateSubmit();
    f.title.focus();
  }
}

async function readHead(file, n) {
  return new Uint8Array(await file.slice(0, n).arrayBuffer());
}

async function checkAudio() {
  const file = f.audio.files[0];
  f.audioErr.hidden = true;
  if (!file) return true;
  const max = defaults?.max_upload_mb;
  let msg = '';
  const b = await readHead(file, 3);
  const isMp3 = (b[0] === 0x49 && b[1] === 0x44 && b[2] === 0x33) || (b[0] === 0xff && (b[1] & 0xe0) === 0xe0);
  if (!isMp3) msg = 'Это не mp3-файл';
  else if (max && file.size > max * 1024 * 1024) msg = `Файл больше ${max} МБ`;
  f.audioErr.textContent = msg;
  f.audioErr.hidden = !msg;
  return !msg;
}

async function checkCover() {
  const file = f.cover.files[0];
  f.coverErr.hidden = true;
  if (!file) return true;
  const max = defaults?.max_cover_mb || 10;
  const b = await readHead(file, 12);
  const jpg = b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff;
  const png = b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47;
  const webp = String.fromCharCode(...b.slice(0, 4)) === 'RIFF' && String.fromCharCode(...b.slice(8, 12)) === 'WEBP';
  let msg = '';
  if (!(jpg || png || webp)) msg = 'Обложка должна быть в формате jpg, png или webp';
  else if (file.size > max * 1024 * 1024) msg = `Файл больше ${max} МБ`;
  f.coverErr.textContent = msg;
  f.coverErr.hidden = !msg;
  return !msg;
}

async function onLyricsFile() {
  const file = f.lyricsFile.files[0];
  f.lyricsErr.hidden = true;
  if (!file) return;
  const max = defaults?.max_lyrics_mb || 1;
  if (file.size > max * 1024 * 1024) {
    f.lyricsErr.textContent = `Файл больше ${max} МБ`;
    f.lyricsErr.hidden = false;
    return;
  }
  const buf = await file.arrayBuffer();
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(buf); // BOM снимается сам
  } catch {
    text = new TextDecoder('windows-1251').decode(buf);
  }
  f.lyrics.value = text.replace(/\r\n?/g, '\n');
  f.lyricsFile.value = '';
  updateLyricsState();
}

function collectParams() {
  const num = (el) => (el.value.trim() === '' ? null : Number(el.value));
  return {
    whisper_model: f.whisper_model.value,
    language: f.language.value,
    compute_type: f.compute_type.value,
    batch_size: num(f.batch_size),
    align_model: f.align_model.value.trim(),
    vad_onset: num(f.vad_onset),
    vad_offset: num(f.vad_offset),
    demucs_model: f.demucs_model.value,
    keep_debug: f.keep_debug.checked,
  };
}

// ---------------------------------------------------------------- отправка

async function onSubmit(ev) {
  ev.preventDefault();
  if (submitting) return;
  f.error.hidden = true;
  const artist = f.artist.value.trim(), title = f.title.value.trim();
  f.artist.value = artist;
  f.title.value = title;
  let ok = true;
  for (const [el, err] of [[f.artist, f.artistErr], [f.title, f.titleErr]]) {
    const bad = !el.value;
    el.classList.toggle('invalid', bad);
    err.hidden = !bad;
    if (bad && ok) el.focus();
    ok = ok && !bad;
  }
  if (!f.audio.files[0] && !regen) {
    f.audioErr.textContent = 'Загрузите mp3-файл';
    f.audioErr.hidden = false;
    ok = false;
  } else if (!(await checkAudio())) {
    ok = false;
  }
  if (!(await checkCover())) ok = false;
  if (!ok) return;

  const fd = new FormData();
  fd.append('artist', artist);
  fd.append('title', title);
  if (f.audio.files[0]) fd.append('audio', f.audio.files[0]);
  fd.append('lyrics', f.lyrics.value);
  if (f.cover.files[0]) fd.append('cover', f.cover.files[0]);
  fd.append('params', JSON.stringify(collectParams()));
  if (regen) fd.append('song_id', regen.song_id);
  fd.append('replace', replace ? 'true' : 'false');

  submitting = true;
  updateSubmit();
  const label = f.submit.textContent;
  f.submit.textContent = 'Отправка…';
  try {
    await api.generate(fd);
    toast(`«${songName(artist, title)}» в очереди`);
    resetForm();
    location.hash = '#queue';
  } catch (e) {
    if (e.status === 409 && e.data.song_id) {
      showDup(e.data.song_id);
      f.dup.scrollIntoView({ block: 'center', behavior: 'smooth' });
    } else {
      f.error.textContent = e.detail;
      f.error.hidden = false;
      if (e.detail === 'Это не mp3-файл') { f.audioErr.textContent = e.detail; f.audioErr.hidden = false; }
    }
  } finally {
    submitting = false;
    f.submit.textContent = label;
    updateSubmit();
  }
}
