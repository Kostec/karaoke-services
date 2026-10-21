// Раздел «Новая песня» (и перегенерация песни из списка: #new?song=<song_id>).
// Звук — mp3-файл или ссылка на трек (audio_url, скачает воркер); одно сбрасывает другое.

import { api, PARAM_KEYS, generateForm, errorText } from './api.js';
import { createVideoBlock, videoChoices, isVideoLink } from './video-block.js';
import { h, clear, toast, debounce, songName, field, confirmDialog } from './ui.js';
import { readId3, planAutofill } from './id3.js';
import {
  searchBlocker, needsReplaceConfirm, REPLACE_QUESTION,
  lrcPlainText, lrcTimingDefault, fmtSeconds, lrcAfterEdit, lrcForNewText, lrcFormPart, lrcShown, LRC_SAVED,
  LRC_TIMING_LABEL,
} from './lyrics-search.js';
import { openLyricsDialog } from './lyrics-dialog.js';
import { linkOutcome, linkCoverUrl, isYandexNoToken, LINK_SERVICES, SETTINGS_LINK_TEXT } from './link-logic.js';


let root, form, f = {}, defaults = null, defaultsError = null;
let regen = null; // карточка песни при перегенерации
let replace = false; // пользователь выбрал «Заменить»
let dupId = null; // song_id совпавшей песни
let submitting = false;
let alignTouched = false;
let existsSeq = 0;
// G07: теги mp3 — значения, подставленные из тегов (их можно заменить тегами другого mp3),
// и обложка из тегов (уходит в «Обложку», если своя не выбрана).
let autoVals = {};
let tagCover = null;
let tagsSeq = 0;
let previewUrl = null;
// G06: LRC рядом с текстом — состояния и что уходит серверу описаны в lyrics-search.js (LRC_SAVED, LRC_DROP).
let lrcHeld = null;
let audioDuration = null; // длительность mp3 из формы, с
let durationSeq = 0;
// Ссылка на трек: link — {input, url, list} последнего «Получить» (url — ссылка на один трек из
// ответа inspect, list — подсказка, если это альбом/плейлист); linkThumb — обложка-превью.
let link = null;
let linkThumb = null;
let linkSeq = 0;
const COVER_EXT = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp' };

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

function select(name, options) {
  return h('select', { name }, options.map(([v, t]) => h('option', { value: v }, t)));
}

async function build() {
  try {
    defaults = await api.defaults();
  } catch (e) {
    defaultsError = errorText(e);
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
  // блок «Видео» (истории 24, 29): «из ссылки песни» — только при yt-dlp-ссылке на звук
  f.video = createVideoBlock({ ...videoChoices({}), maxMb: d.max_video_mb, heights: d.video_heights,
    defaultHeight: d.default_video_height });
  f.audioHint = h('div', { class: 'small muted' });
  f.audioErr = h('div', { class: 'field-error', hidden: true });
  f.audioUrl = h('input', { type: 'text', name: 'audio_url', inputmode: 'url', autocomplete: 'off',
    placeholder: 'https://…', 'aria-label': 'Ссылка на трек', style: 'flex:1;min-width:12em' });
  f.linkBtn = h('button', { type: 'button', onclick: onGetLink }, 'Получить');
  f.linkInfo = h('div', { class: 'small muted', hidden: true });
  f.linkErr = h('div', { class: 'field-error', hidden: true });

  f.lyrics = h('textarea', { name: 'lyrics', rows: '10', placeholder: 'Вставьте текст песни или выберите файл .txt / .lrc' });
  f.lyricsFile = h('input', { type: 'file', accept: '.txt,.lrc,text/plain', 'aria-label': 'Файл текста' });
  f.lyricsWarn = h('div', { class: 'banner warn small' }, 'Без текста слова будут распознаны автоматически — качество ниже');
  f.lyricsErr = h('div', { class: 'field-error', hidden: true });
  f.findLyrics = h('button', { type: 'button', onclick: onFindLyrics }, 'Найти текст');
  f.findHint = h('span', { class: 'small muted' });
  f.lrc_timing = h('input', { type: 'checkbox', name: 'lrc_timing' });
  f.lrcHint = h('div', { class: 'small muted' });
  f.lrcBox = h('div', { hidden: true }, h('label', { class: 'check' }, f.lrc_timing, LRC_TIMING_LABEL), f.lrcHint);

  f.cover = h('input', { type: 'file', name: 'cover', accept: '.jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp' });
  f.coverErr = h('div', { class: 'field-error', hidden: true });
  f.tagsHint = h('div', { class: 'small muted', hidden: true });
  f.coverImg = h('img', { alt: 'Превью обложки', style: 'width:72px;height:72px;object-fit:cover;border-radius:6px;border:1px solid var(--border)' });
  f.coverNote = h('span', { class: 'small muted' });
  f.coverPreview = h('div', { class: 'cover-preview', hidden: true, style: 'display:flex;align-items:center;gap:10px;margin-top:6px;flex-wrap:wrap' },
    f.coverImg, f.coverNote,
    h('button', { type: 'button', onclick: removeCover }, 'Убрать'));

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
    field('Аудио mp3', f.audio, d.max_upload_mb ? `до ${d.max_upload_mb} МБ` : null), f.audioHint, f.audioErr, f.tagsHint,
    h('div', { class: 'field' },
      h('span', {}, 'или ссылка на трек', h('span', { class: 'hint' }, ` (${LINK_SERVICES})`)),
      h('div', { class: 'inline-file' }, f.audioUrl, f.linkBtn),
      f.linkInfo, f.linkErr),
    f.video.el,
    h('div', { class: 'field' },
      h('span', {}, 'Текст песни', h('span', { class: 'hint' }, ' (можно оставить пустым)')),
      f.lyrics,
      h('div', { class: 'inline-file' }, h('span', { class: 'small muted' }, 'или файл:'), f.lyricsFile,
        f.findLyrics, f.findHint),
      f.lyricsErr, f.lrcBox),
    f.lyricsWarn,
    field('Обложка', f.cover, d.max_cover_mb ? `jpg, png или webp до ${d.max_cover_mb} МБ, необязательно` : 'jpg, png или webp, необязательно'), f.coverErr, f.coverPreview,
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
      updateFindLyrics();
      onName();
    });
  }
  f.lyrics.addEventListener('input', () => {
    setLrc(lrcAfterEdit(lrcHeld, f.lyrics.value, !!regen));
    updateLyricsState();
  });
  f.lrc_timing.addEventListener('change', () => { f.lrcHint.textContent = ''; });
  f.lyricsFile.addEventListener('change', onLyricsFile);
  f.audio.addEventListener('change', async () => {
    if (f.audio.files[0]) clearLink(true); // файл важнее ссылки — ссылка сбрасывается
    refreshVideo();
    readAudioDuration(f.audio.files[0]);
    if (await checkAudio()) autofillFromTags(f.audio.files[0]);
  });
  f.audioUrl.addEventListener('input', onLinkInput);
  f.audioUrl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); onGetLink(); } });
  f.cover.addEventListener('change', async () => { await checkCover(); updateCoverPreview(); });
  f.language.addEventListener('change', () => {
    if (!alignTouched) f.align_model.value = (defaults?.align_models || {})[f.language.value] || '';
  });
  f.align_model.addEventListener('input', () => { alignTouched = true; });

  clear(root).append(h('div', { class: 'view-head' }, h('h2', { id: 'new-title' }, 'Новая песня')));
  if (defaultsError) root.append(h('div', { class: 'banner err' }, `Не удалось загрузить настройки формы: ${defaultsError}`));
  root.append(form);
  setParams(d.defaults || {});
  updateLyricsState();
  updateFindLyrics();
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
  f.video.reset('none');
  regen = null;
  replace = false;
  dupId = null;
  f.dup.hidden = true;
  f.error.hidden = true;
  f.regenBanner.hidden = true;
  f.cancelRegen.hidden = true;
  f.audioHint.textContent = '';
  autoVals = {};
  tagCover = null;
  tagsSeq++;
  f.tagsHint.hidden = true;
  updateCoverPreview();
  audioDuration = null;
  durationSeq++;
  clearLink(true);
  setLrc(null);
  for (const e of [f.audioErr, f.coverErr, f.lyricsErr, f.artistErr, f.titleErr]) e.hidden = true;
  for (const e of [f.artist, f.title]) e.classList.remove('invalid');
  document.getElementById('new-title').textContent = 'Новая песня';
  setParams(defaults?.defaults || {});
  updateLyricsState();
  updateFindLyrics();
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
    updateFindLyrics();
    if (song.params) setParams({ ...(defaults?.defaults || {}), ...song.params });
    let text = song.lyrics;
    if (text == null) {
      try { text = (await api.lyrics(songId)).text; } catch (e) { toast(`Текст не загрузился: ${errorText(e)}`, 'err'); }
    }
    f.lyrics.value = text || '';
    // тайминги из сохранённого source/lyrics.lrc: сервер возьмёт его сам, галочка — из params песни
    // без галочки сохранённый LRC (если есть) тоже не трогается: поле lyrics_lrc не уйдёт
    if (song.params?.lrc_timing && f.lyrics.value.trim()) setLrc(LRC_SAVED, false);
    f.regenBanner.textContent = `Перегенерация «${songName(song.artist, song.title)}». После успеха старая версия уйдёт в корзину.`;
    f.audioHint.textContent = song.own
      ? 'Можно не выбирать: возьмётся mp3 из исходников песни.'
      : 'Можно не выбирать: возьмётся аудио из папки песни.';
    f.cancelRegen.hidden = false;
  } catch (e) {
    regen = null;
    f.regenBanner.textContent = `Не удалось открыть песню: ${errorText(e)}`;
    f.regenBanner.className = 'banner err';
    return;
  } finally {
    f.submit.disabled = false;
    updateLyricsState();
  }
  f.regenBanner.className = 'banner warn';
}

// ---------------------------------------------------------------- поиск текста (R01)

function updateFindLyrics() {
  const why = searchBlocker(f.artist.value, f.title.value);
  f.findLyrics.disabled = !!why;
  f.findLyrics.title = why;
  f.findHint.textContent = why;
}

function onFindLyrics() {
  const artist = f.artist.value.trim(), title = f.title.value.trim();
  if (searchBlocker(artist, title)) return;
  f.findLyrics.disabled = true;
  openLyricsDialog({ artist, title, onPick: insertLyrics, onSettled: updateFindLyrics });
}

async function insertLyrics(hit) {
  // G06.1: у синхронизированного варианта текст строится из LRC (строка с N метками — N раз),
  // иначе строки не совпадут с метками и тайминги не применятся
  const fromLrc = hit.synced ? lrcPlainText(hit.synced) : '';
  const text = fromLrc || hit.text;
  if (needsReplaceConfirm(f.lyrics.value) && f.lyrics.value.trim() !== text.trim()) {
    if (!(await confirmDialog(REPLACE_QUESTION, 'Заменить'))) return false; // список вариантов остаётся открытым
  }
  setLrc(lrcForNewText(fromLrc ? hit : null, !!regen));
  f.lyrics.value = text;
  f.lyricsErr.hidden = true;
  f.lyrics.classList.remove('invalid');
  updateLyricsState();
  toast('Текст вставлен');
  return true; // закрыть диалог
}

/** Держать LRC (или сбросить: null); recheck — заново выставить галочку по правилу 3 с. */
function setLrc(held, recheck = true) {
  const changed = held !== lrcHeld;
  lrcHeld = held;
  f.lrcBox.hidden = !lrcShown(held);
  if (!lrcShown(held)) {
    f.lrc_timing.checked = false;
    f.lrcHint.textContent = '';
  } else if (changed && recheck) {
    applyLrcDefault();
  }
}

function applyLrcDefault() {
  if (!lrcShown(lrcHeld) || lrcHeld.lrc == null) return;
  const { checked, hint } = lrcTimingDefault(lrcHeld.duration, audioDuration);
  f.lrc_timing.checked = checked;
  f.lrcHint.textContent = hint;
}

/** Длительность mp3 из формы (метаданные через <audio>), затем — правило 3 с для LRC. */
function readAudioDuration(file) {
  const seq = ++durationSeq;
  audioDuration = null;
  if (!file) { applyLrcDefault(); return; }
  const url = URL.createObjectURL(file);
  const el = new Audio();
  const done = (sec) => {
    URL.revokeObjectURL(url);
    if (seq !== durationSeq) return;
    audioDuration = Number.isFinite(sec) && sec > 0 ? sec : null;
    applyLrcDefault();
  };
  el.preload = 'metadata';
  el.addEventListener('loadedmetadata', () => done(el.duration), { once: true });
  el.addEventListener('error', () => done(null), { once: true });
  el.src = url;
}

// ---------------------------------------------------------------- ссылка на трек

/** Сбросить ссылку (выбран файл / сброс формы); input — очистить и поле. */
function clearLink(input) {
  linkSeq++;
  if (input) f.audioUrl.value = '';
  f.audioUrl.classList.remove('invalid');
  const hadLink = !!link;
  link = null;
  linkThumb = null;
  f.linkInfo.hidden = true;
  f.linkErr.hidden = true;
  f.linkBtn.disabled = false;
  f.linkBtn.textContent = 'Получить';
  updateCoverPreview();
  if (hadLink && !f.audio.files[0]) { audioDuration = null; durationSeq++; applyLrcDefault(); }
}

/** Варианты блока «Видео» по звуку: ссылка yt-dlp (не Яндекс) — есть «из ссылки песни». */
function refreshVideo() {
  if (!f.video) return;
  const url = f.audio.files[0] ? '' : audioUrlValue();
  const source = isVideoLink(url);
  f.video.setModes(videoChoices({ source }).modes);
  f.video.setSource(source ? url : '');
}

/** Ввод ссылки: файл сбрасывается (вместе с обложкой из его тегов); прежний «Получить» устарел. */
function onLinkInput() {
  if (f.audioUrl.value.trim() && f.audio.files[0]) {
    f.audio.value = '';
    f.audioErr.hidden = true;
    tagCover = null;
    tagsSeq++;
    f.tagsHint.hidden = true;
    audioDuration = null;
    durationSeq++;
    applyLrcDefault();
    updateCoverPreview();
  }
  if (link && f.audioUrl.value.trim() !== link.input) clearLink(false);
  f.linkErr.hidden = true;
  f.audioErr.hidden = true;
  refreshVideo();
}

function showLinkError(text, e) {
  f.linkErr.textContent = text;
  if (isYandexNoToken(e)) f.linkErr.append(' ', h('a', { href: '#settings' }, SETTINGS_LINK_TEXT));
  f.linkErr.hidden = !text;
}

/** «Получить»: link/inspect → исполнитель/название (если пусты), обложка-превью, длительность для LRC. */
async function onGetLink() {
  const input = f.audioUrl.value.trim();
  if (!input) { showLinkError('Вставьте ссылку на трек'); f.audioUrl.focus(); return; }
  onLinkInput();
  const my = ++linkSeq;
  f.linkBtn.disabled = true;
  f.linkBtn.textContent = 'Получаю…';
  f.linkErr.hidden = true;
  f.linkInfo.hidden = true;
  try {
    const info = await api.linkInspect(input);
    if (my !== linkSeq) return;
    const out = linkOutcome(info);
    if (out.kind !== 'track') {
      link = { input, url: '', list: out.kind === 'list' ? out.text : '' };
      linkThumb = null;
      showLinkError(out.text);
      if (out.kind === 'list') f.linkErr.append(' ', h('a', { href: '#import' }, 'Открыть Импорт'));
      return;
    }
    const t = out.track;
    link = { input, url: t.url || input, list: '' };
    linkThumb = t.thumbnail || null;
    const plan = planAutofill({ artist: f.artist.value, title: f.title.value }, t, autoVals);
    for (const [k, v] of Object.entries(plan)) {
      f[k].value = v;
      f[k].classList.remove('invalid');
      (k === 'artist' ? f.artistErr : f.titleErr).hidden = true;
    }
    autoVals = { ...autoVals, ...plan };
    const sec = Number(t.duration);
    audioDuration = sec > 0 ? sec : null; // правило 3 с для таймингов LRC — по длительности трека
    durationSeq++;
    applyLrcDefault();
    const what = [songName(t.artist, t.title), fmtSeconds(t.duration)].filter(Boolean).join(' · ');
    f.linkInfo.textContent = `Трек: ${what || t.url}`;
    f.linkInfo.hidden = false;
    updateCoverPreview();
    updateFindLyrics();
    if (plan.artist || plan.title) {
      replace = false;
      checkExists();
    }
  } catch (e) {
    if (my !== linkSeq) return;
    showLinkError(errorText(e), e);
    f.audioUrl.classList.add('invalid');
  } finally {
    if (my === linkSeq) { f.linkBtn.disabled = false; f.linkBtn.textContent = 'Получить'; }
  }
}

/** Что уходит в audio_url: ссылка на трек из «Получить» или введённая как есть. */
function audioUrlValue() {
  const input = f.audioUrl.value.trim();
  if (!input) return '';
  return link && link.input === input && link.url ? link.url : input;
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
  refreshVideo(); // «Получить» могло заменить ссылку на трек
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
  const max = defaults?.max_cover_mb;
  const b = await readHead(file, 12);
  const jpg = b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff;
  const png = b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47;
  const webp = String.fromCharCode(...b.slice(0, 4)) === 'RIFF' && String.fromCharCode(...b.slice(8, 12)) === 'WEBP';
  let msg = '';
  if (!(jpg || png || webp)) msg = 'Обложка должна быть в формате jpg, png или webp';
  else if (max && file.size > max * 1024 * 1024) msg = `Файл больше ${max} МБ`;
  f.coverErr.textContent = msg;
  f.coverErr.hidden = !msg;
  return !msg;
}

// ---------------------------------------------------------------- теги mp3 (G07)

async function autofillFromTags(file) {
  const my = ++tagsSeq;
  tagCover = null;
  f.tagsHint.hidden = true;
  if (!file) { updateCoverPreview(); return; }
  let tags;
  try {
    tags = await readId3(file);
  } catch {
    tags = { artist: '', title: '', cover: null }; // нечитаемые теги — просто без автозаполнения
  }
  if (my !== tagsSeq) return;
  const plan = planAutofill({ artist: f.artist.value, title: f.title.value }, tags, autoVals);
  const filled = [];
  for (const [k, v] of Object.entries(plan)) {
    f[k].value = v;
    f[k].classList.remove('invalid');
    (k === 'artist' ? f.artistErr : f.titleErr).hidden = true;
    filled.push(k === 'artist' ? 'исполнитель' : 'название');
  }
  autoVals = { ...autoVals, ...plan };
  const c = tags.cover;
  const max = defaults?.max_cover_mb;
  if (c && COVER_EXT[c.mime] && !(max && c.data.length > max * 1024 * 1024)) {
    tagCover = new File([c.data], `cover.${COVER_EXT[c.mime]}`, { type: c.mime });
    filled.push('обложка');
  }
  f.tagsHint.textContent = filled.length ? `Из тегов mp3: ${filled.join(', ')} — можно поправить` : '';
  f.tagsHint.hidden = !filled.length;
  updateCoverPreview();
  if (plan.artist || plan.title) {
    replace = false;
    checkExists();
  }
}

/** Превью обложки: своя из формы важнее обложки из тегов mp3. */
function updateCoverPreview() {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  const own = f.cover.files[0] && f.coverErr.hidden ? f.cover.files[0] : null;
  const file = own || tagCover;
  const thumb = currentLinkCover();
  f.coverPreview.hidden = !file && !thumb;
  if (thumb) { // обложку со ссылки (cover_url) скачает сервис, если своей нет
    f.coverImg.setAttribute('referrerpolicy', 'no-referrer');
    f.coverImg.src = thumb;
    f.coverNote.textContent = 'Обложка со ссылки — выберите файл выше, чтобы заменить';
    return;
  }
  f.coverImg.removeAttribute('referrerpolicy');
  if (!file) { f.coverImg.removeAttribute('src'); return; }
  previewUrl = URL.createObjectURL(file);
  f.coverImg.src = previewUrl;
  f.coverNote.textContent = own ? 'Своя обложка' : 'Обложка из тегов mp3 — выберите файл выше, чтобы заменить';
}

/** Обложка со ссылки, которая уйдёт в generate (cover_url): своя обложка важнее. */
function currentLinkCover() {
  const own = f.cover.files[0] || tagCover;
  return linkCoverUrl({ ownCover: own, audioFile: f.audio.files[0], link, input: f.audioUrl.value, thumb: linkThumb });
}

function removeCover() {
  f.cover.value = '';
  f.coverErr.hidden = true;
  tagCover = null;
  updateCoverPreview();
}

async function onLyricsFile() {
  const file = f.lyricsFile.files[0];
  f.lyricsErr.hidden = true;
  if (!file) return;
  const max = defaults?.max_lyrics_mb;
  if (max && file.size > max * 1024 * 1024) {
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
  setLrc(lrcForNewText(null, !!regen)); // текст из файла — не тот, к которому LRC
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
    lrc_timing: lrcShown(lrcHeld) && f.lrc_timing.checked,
  };
}

// ---------------------------------------------------------------- отправка

/** Подсветить поле по машиночитаемому `field` из ответа сервера. */
function markField(name, detail) {
  const errs = { artist: f.artistErr, title: f.titleErr, audio: f.audioErr, cover: f.coverErr, lyrics: f.lyricsErr,
    audio_url: f.linkErr };
  const inputs = { lyrics: f.lyrics, audio_url: f.audioUrl };
  const el = inputs[name] || f[name];
  if (!name || !el || !(el instanceof HTMLElement)) return;
  if (errs[name]) {
    errs[name].textContent = detail;
    errs[name].hidden = false;
  }
  const details = el.closest('details'); // whisper_model и language — вне «Дополнительно»
  if (details) details.open = true;
  el.classList.add('invalid');
  el.addEventListener('input', () => el.classList.remove('invalid'), { once: true });
  el.addEventListener('change', () => el.classList.remove('invalid'), { once: true });
  el.focus();
}

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
  const audioUrl = f.audio.files[0] ? '' : audioUrlValue();
  if (!f.audio.files[0] && !audioUrl && !regen) {
    f.audioErr.textContent = 'Загрузите mp3-файл или вставьте ссылку на трек';
    f.audioErr.hidden = false;
    ok = false;
  } else if (audioUrl && link?.list && link.input === f.audioUrl.value.trim()) {
    showLinkError(link.list); // альбом/плейлист — это «Импорт → Ссылка»
    f.linkErr.append(' ', h('a', { href: '#import' }, 'Открыть Импорт'));
    f.audioUrl.focus();
    ok = false;
  } else if (!(await checkAudio())) {
    ok = false;
  }
  if (!(await checkCover())) ok = false;
  refreshVideo();
  if (!f.video.validate()) ok = false;
  if (!ok) return;

  const fd = generateForm({
    artist, title, lyrics: f.lyrics.value, params: collectParams(),
    audio: f.audio.files[0], audio_url: audioUrl, cover: f.cover.files[0] || tagCover,
    cover_url: currentLinkCover() || undefined,
    song_id: regen?.song_id, replace,
    lyrics_lrc: lrcFormPart(lrcHeld), // передать / сбросить сохранённый / не трогать
    ...f.video.fields(),
  });

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
      f.error.textContent = errorText(e);
      if (isYandexNoToken(e)) f.error.append(' ', h('a', { href: '#settings' }, SETTINGS_LINK_TEXT));
      f.error.hidden = false;
      if (!f.video.showApiError(e)) markField(e.data?.field, errorText(e));
    }
  } finally {
    submitting = false;
    f.submit.textContent = label;
    updateSubmit();
  }
}
