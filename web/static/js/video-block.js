// Блок «Видео»: выбор источника (режимы — параметр), ссылка и качество, файл, смещение.
// Общий для диалога «Видео…» на карточке песни, «Новой песни» и импорта.
// Чистая часть (videoFields, videoError, normGap, память качества) — под node-тесты.

import { h } from './ui.js';

/** Все режимы: none — без видео, source — из ссылки песни/usdb, url — своя ссылка, file — файл, pack — из архива. */
export const VIDEO_MODES = ['none', 'source', 'url', 'file', 'pack'];
export const MODE_LABELS = {
  none: 'Без видео', source: 'Из ссылки песни', url: 'Своя ссылка', file: 'Файл', pack: 'Из архива',
};
// Качества и расширения приходят из /api/defaults (video_heights, default_video_height, video_exts —
// naming.VIDEO_EXT_ORDER); эти списки — только запасные, если сервер не ответил.
export const VIDEO_HEIGHTS = [360, 480, 720, 1080, 0]; // 0 — лучшее
export const DEFAULT_VIDEO_HEIGHT = 720;
export const VIDEO_EXTS = ['.mp4', '.m4v', '.mkv', '.webm', '.avi', '.mov', '.mpg', '.mpeg'];
export const HEIGHT_KEY = 'video.height';
const GAP_ERROR = 'Смещение видео — число секунд, например 1.5 или -0.25';

export function heightLabel(height) {
  return Number(height) === 0 ? 'лучшее' : `${height}p`;
}

/** Смещение для отправки: запятая → точка, без пробелов; пусто — ''. */
export function normGap(value) {
  return String(value ?? '').trim().replace(',', '.');
}

/**
 * Поля multipart блока для generate/import: {video_mode, video_url?, video_file?, video_height?, videogap?}.
 * state — {mode, url, file, height, gap}; лишнее для режима не уходит, пустое смещение — тоже.
 */
export function videoFields(state = {}) {
  const mode = VIDEO_MODES.includes(state.mode) ? state.mode : 'none';
  const out = { video_mode: mode };
  if (mode === 'none') return out;
  if (mode === 'url') out.video_url = String(state.url ?? '').trim();
  if (mode === 'file') out.video_file = state.file;
  if (mode === 'url' || mode === 'source') out.video_height = String(state.height ?? DEFAULT_VIDEO_HEIGHT);
  const gap = normGap(state.gap);
  if (gap) out.videogap = gap;
  return out;
}

/**
 * Варианты блока при создании песни: source — есть ссылка на видео (звук по yt-dlp-ссылке,
 * v= usdb), pack — видеофайл из архива. По умолчанию «без видео», а при видео из архива — оно.
 */
export function videoChoices({ source = false, pack = false } = {}) {
  const modes = VIDEO_MODES.filter((m) => (m === 'source' ? source : m === 'pack' ? pack : true));
  return { modes, mode: pack ? 'pack' : 'none' };
}

const extList = (exts) => (Array.isArray(exts) && exts.length ? exts : VIDEO_EXTS);

/** accept поля файла из списка расширений (/api/defaults::video_exts). */
export function videoAccept(exts) {
  return extList(exts).join(',');
}

/** Подсказка у поля файла: «mp4, mkv…; до N МБ». */
export function fileHint(exts, maxMb) {
  const names = extList(exts).map((e) => String(e).replace(/^\./, '')).join(', ');
  return maxMb ? `${names}; до ${maxMb} МБ` : names;
}

// Как api_jobs.parse_videogap: [+-]цифры[.цифры] или [+-].цифры (после normGap), конечное число.
const GAP_RE = /^[-+]?(\d+\.?\d*|\.\d+)$/;

/** Ошибка заполнения до отправки: {field, text} (field — как у API) или null. */
export function videoError(state = {}) {
  const mode = state.mode || 'none';
  if (mode === 'none') return null;
  if (mode === 'url' && !String(state.url ?? '').trim()) return { field: 'video_url', text: 'Вставьте ссылку на видео' };
  if (mode === 'file' && !state.file) return { field: 'video', text: 'Выберите видеофайл' };
  const gap = normGap(state.gap);
  if (gap && !(GAP_RE.test(gap) && Number.isFinite(Number(gap)))) return { field: 'videogap', text: GAP_ERROR };
  return null;
}

function storage(ls) {
  if (ls) return ls;
  try { return globalThis.localStorage; } catch { return null; }
}

/** Последнее выбранное качество из localStorage `video.height`; нет/чужое/сбой — dflt. */
export function rememberedHeight(heights = VIDEO_HEIGHTS, dflt = DEFAULT_VIDEO_HEIGHT, ls) {
  try {
    const raw = storage(ls)?.getItem(HEIGHT_KEY);
    const v = raw === null || raw === undefined || raw === '' ? NaN : Number(raw);
    return heights.includes(v) ? v : dflt;
  } catch {
    return dflt;
  }
}

export function rememberHeight(height, ls) {
  try { storage(ls)?.setItem(HEIGHT_KEY, String(height)); } catch { /* приватный режим — не страшно */ }
}

/**
 * Разметка блока. opts: {modes (какие показать, порядок — как в VIDEO_MODES), mode (начальный),
 * labels ({режим: подпись} поверх MODE_LABELS), sourceUrl (ссылка для режима source),
 * heights, defaultHeight, exts (расширения файла), gap (начальное смещение), maxMb (лимит файла), onChange(state)}.
 * Возвращает {el, state() (+ gapTouched), fields(), setMode, setModes(modes, mode?), setSource(url), setGap, reset(mode?, gap?),
 * validate() → bool (ошибка — у поля), showError(field, text), showApiError(e) → bool, clearErrors()}.
 */
export function createVideoBlock(opts = {}) {
  const heights = opts.heights || VIDEO_HEIGHTS;
  const labels = { ...MODE_LABELS, ...(opts.labels || {}) };
  const onChange = opts.onChange || (() => {});
  let modes = [];

  const modeSel = h('select', { 'aria-label': 'Видео', name: 'video_mode' });
  const urlIn = h('input', { type: 'text', inputmode: 'url', name: 'video_url', placeholder: 'https://www.youtube.com/watch?v=…',
    'aria-label': 'Ссылка на видео', autocomplete: 'off' });
  const heightSel = h('select', { name: 'video_height', 'aria-label': 'Качество видео' },
    heights.map((v) => h('option', { value: String(v) }, heightLabel(v))));
  heightSel.value = String(rememberedHeight(heights, opts.defaultHeight ?? DEFAULT_VIDEO_HEIGHT));
  const fileIn = h('input', { type: 'file', name: 'video', accept: videoAccept(opts.exts), 'aria-label': 'Видеофайл' });
  const gapIn = h('input', { type: 'text', name: 'videogap', inputmode: 'decimal', class: 'video-gap',
    value: opts.gap ?? '', 'aria-label': 'Смещение видео, с' });
  const sourceEl = h('div', { class: 'small muted video-source' });

  const errs = {};
  const inputs = { video_mode: modeSel, video_url: urlIn, video_height: heightSel, video: fileIn, videogap: gapIn };
  const errEl = (key) => (errs[key] = h('div', { class: 'field-error', hidden: true, role: 'alert' }));

  const hint = fileHint(opts.exts, opts.maxMb);
  const rows = {
    url: h('label', { class: 'field' }, h('span', {}, 'Ссылка на видео',
      h('span', { class: 'hint' }, ' (YouTube, VK Видео, RuTube…)')), urlIn, errEl('video_url')),
    height: h('label', { class: 'field' }, h('span', {}, 'Качество'), heightSel, errEl('video_height')),
    file: h('label', { class: 'field' }, h('span', {}, 'Видеофайл', h('span', { class: 'hint' }, ` (${hint})`)),
      fileIn, errEl('video')),
    gap: h('label', { class: 'field' }, h('span', {}, 'Смещение видео, с',
      h('span', { class: 'hint' }, ' (+ — видео позже, − — раньше)')), gapIn, errEl('videogap')),
  };
  const el = h('div', { class: 'video-block' },
    h('label', { class: 'field video-mode' }, h('span', {}, 'Видео'), modeSel, errEl('video_mode')),
    sourceEl, rows.url, rows.height, rows.file, rows.gap);

  let gapTouched = false; // пользователь сам правил смещение (диалог не перетирает его текущим у песни)

  function state() {
    return { mode: modeSel.value || 'none', url: urlIn.value, file: fileIn.files?.[0] || null,
      height: Number(heightSel.value), gap: gapIn.value, gapTouched };
  }

  function sync() {
    const m = state().mode;
    rows.url.hidden = m !== 'url';
    rows.height.hidden = m !== 'url' && m !== 'source';
    rows.file.hidden = m !== 'file';
    rows.gap.hidden = m === 'none';
    sourceEl.hidden = m !== 'source' || !sourceEl.textContent;
  }

  function clearErrors() {
    for (const [key, e] of Object.entries(errs)) {
      e.hidden = true;
      e.textContent = '';
      inputs[key]?.classList.remove('invalid');
    }
  }

  function showError(key, text) {
    if (key === 'video_file') key = 'video'; // generate/import называют файл video_file
    const target = errs[key] ? key : 'video_mode';
    errs[target].textContent = text;
    errs[target].hidden = false;
    inputs[target]?.classList.add('invalid');
  }

  function setModes(list, mode) {
    modes = VIDEO_MODES.filter((m) => list.includes(m));
    const keep = mode ?? (modes.includes(modeSel.value) ? modeSel.value : modes[0]);
    modeSel.replaceChildren(...modes.map((m) => h('option', { value: m }, labels[m])));
    modeSel.value = modes.includes(keep) ? keep : modes[0];
    modeSel.disabled = modes.length < 2;
    sync();
  }

  const changed = () => { clearErrors(); sync(); onChange(state()); };
  modeSel.addEventListener('change', changed);
  heightSel.addEventListener('change', () => { rememberHeight(Number(heightSel.value)); changed(); });
  gapIn.addEventListener('input', () => { gapTouched = true; });
  for (const i of [urlIn, fileIn, gapIn]) i.addEventListener('input', changed);
  fileIn.addEventListener('change', changed);

  setModes(opts.modes || ['none', 'url', 'file'], opts.mode);
  if (opts.sourceUrl) sourceEl.textContent = opts.sourceUrl;
  sync();

  return {
    el,
    state,
    fields: () => videoFields(state()),
    setMode: (m) => { if (modes.includes(m)) { modeSel.value = m; sync(); } },
    setModes,
    setSource: (url) => { sourceEl.textContent = url || ''; sync(); },
    setGap: (v) => { gapIn.value = v ?? ''; },
    /** Сбросить: режим, ссылка, файл, смещение (gap) и флаг правки смещения. */
    reset(mode, gap = '') {
      urlIn.value = '';
      fileIn.value = '';
      gapIn.value = gap;
      gapTouched = false;
      clearErrors();
      if (mode !== undefined) setModes(modes, mode); else sync();
    },
    validate() {
      clearErrors();
      const err = videoError(state());
      if (err) showError(err.field, err.text);
      return !err;
    },
    showError,
    /** Ошибка API с полем блока (video_mode, video, video_file, video_url, video_height, videogap) → у поля, true. */
    showApiError(e) {
      const key = e?.data?.field;
      if (!key || !(key in inputs || key === 'video_file')) return false;
      showError(key, e.detail || e.message || 'Ошибка');
      return true;
    },
    clearErrors,
  };
}
