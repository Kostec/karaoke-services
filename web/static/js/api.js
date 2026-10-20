// Обращения к REST API. Ошибка сервера — ApiError с текстом detail (по-русски).

export class ApiError extends Error {
  constructor(status, detail, data = {}) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.data = data;
  }
}

const STATUS_TEXT = {
  401: 'Нужен пароль для входа',
  404: 'Не найдено',
  413: 'Файл слишком большой',
  502: 'Сервер недоступен',
  503: 'Сервис временно недоступен',
  504: 'Сервер не ответил вовремя',
};

export async function request(method, url, body, { binary = false } = {}) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(url, opts);
  } catch {
    throw new ApiError(0, 'Нет связи с сервером — проверьте сеть');
  }
  if (resp.ok && binary) return new Uint8Array(await resp.arrayBuffer());
  const type = resp.headers.get('content-type') || '';
  let data = null;
  if (type.includes('application/json')) {
    try { data = await resp.json(); } catch { data = null; }
  } else {
    data = await resp.text();
  }
  if (!resp.ok) {
    const detail = (data && typeof data === 'object' && typeof data.detail === 'string' && data.detail)
      || STATUS_TEXT[resp.status] || `Ошибка сервера (код ${resp.status})`;
    throw new ApiError(resp.status, detail, data && typeof data === 'object' ? data : {});
  }
  return data;
}

// Состояния заданий — как karaoke_core.db.ACTIVE_STATES / FINAL_STATES.
export const JOB_ACTIVE = ['queued', 'running', 'publishing'];
export const JOB_FINAL = ['done', 'failed', 'cancelled'];
// karaoke_core.db.STAGE_PUBLISH: стадия упавшей выкладки.
export const STAGE_PUBLISH = 'publish';

/** «Выложить повторно» — то же правило, что в web/app/api_jobs.py::republish. */
export function canRepublish(job) {
  return job.state === 'failed' && (job.type === 'publish' || job.stage === STAGE_PUBLISH);
}

let defaultsPromise = null;

/** /api/defaults один раз на страницу: модели, языки, умолчания, лимиты, срок корзины. */
export function getDefaults() {
  if (!defaultsPromise) {
    defaultsPromise = request('GET', '/api/defaults').catch((e) => { defaultsPromise = null; throw e; });
  }
  return defaultsPromise;
}

export const api = {
  status: () => request('GET', '/api/status'),
  defaults: getDefaults,

  jobs: (limit = 50) => request('GET', `/api/jobs?limit=${limit}`),
  generate: (form) => request('POST', '/api/jobs/generate', form),
  instrumental: (songId, replace) => request('POST', '/api/jobs/instrumental', { song_id: songId, replace }),
  cancel: (id) => request('POST', `/api/jobs/${id}/cancel`),
  restart: (id) => request('POST', `/api/jobs/${id}/restart`),
  republish: (id) => request('POST', `/api/jobs/${id}/republish`),
  logStreamUrl: (id) => `/api/jobs/${id}/log/stream`,
  logFrom: (id, from) => request('GET', `/api/jobs/${id}/log?from=${from}`, undefined, { binary: true }),

  songs: (q = '') => request('GET', '/api/songs' + (q ? `?q=${encodeURIComponent(q)}` : '')),
  rescan: () => request('POST', '/api/songs/rescan'),
  exists: (artist, title) =>
    request('GET', `/api/songs/exists?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`),
  song: (id) => request('GET', `/api/songs/${encodeURIComponent(id)}`),
  lyrics: (id) => request('GET', `/api/songs/${encodeURIComponent(id)}/lyrics`),
  notes: (id) => request('GET', `/api/songs/${encodeURIComponent(id)}/notes`),
  saveNotes: (id, body) => request('PUT', `/api/songs/${encodeURIComponent(id)}/notes`, body),
  coverUrl: (id) => `/api/songs/${encodeURIComponent(id)}/cover`,
  audioUrl: (id) => `/api/songs/${encodeURIComponent(id)}/audio`,
  deleteSong: (id) => request('DELETE', `/api/songs/${encodeURIComponent(id)}`),

  lyricsSearch: (artist, title) =>
    request('GET', `/api/lyrics/search?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`),

  trash: () => request('GET', '/api/trash'),
  restore: (id) => request('POST', `/api/trash/${encodeURIComponent(id)}/restore`),

  output: () => request('GET', '/api/settings/output'),
  saveOutput: (body) => request('PUT', '/api/settings/output', body),
  testOutput: (body) => request('POST', '/api/settings/output/test', body),
  usdbAccount: () => request('GET', '/api/settings/usdb'),
  saveUsdbAccount: (body) => request('PUT', '/api/settings/usdb', body),
  testUsdbAccount: (body) => request('POST', '/api/settings/usdb/test', body),
  usdbSearch: ({ artist = '', title = '', language = 'Russian', start = 0 } = {}) =>
    request('GET', `/api/usdb/search?${new URLSearchParams({ artist, title, language, start: String(start) })}`),

  importInspect: (form) => request('POST', '/api/import/inspect', form),
  importJob: (form) => request('POST', '/api/jobs/import', form),
};

// ---------------------------------------------------------------- общие помощники

/** Текст ошибки для пользователя: detail сервера, иначе message, иначе запасной. */
export function errorText(e, fallback = 'Ошибка') {
  return (e && (e.detail || e.message)) || fallback;
}

/** Параметры генерации, которые принимает POST /api/jobs/generate (поле params). */
export const PARAM_KEYS = ['whisper_model', 'language', 'compute_type', 'batch_size', 'align_model',
  'vad_onset', 'vad_offset', 'demucs_model', 'keep_debug', 'lrc_timing'];

/** Только известные параметры; undefined отбрасывается. */
export function pickParams(src = {}) {
  const out = {};
  for (const k of PARAM_KEYS) if (src && src[k] !== undefined) out[k] = src[k];
  return out;
}

/**
 * multipart для POST /api/jobs/generate — единственное место сборки (форма и редактор текста).
 * {artist, title, lyrics, params, audio?, cover?, song_id?, replace?, lyrics_lrc?}
 * lyrics_lrc — LRC файловой частью: строка — взять её ('' — сбросить сохранённый), нет — не трогать.
 */
export function generateForm({ artist, title, lyrics = '', params = {}, audio, cover, song_id: songId, replace = false,
  lyrics_lrc: lrc }) {
  const fd = new FormData();
  fd.append('artist', artist);
  fd.append('title', title);
  if (audio) fd.append('audio', audio);
  fd.append('lyrics', lyrics);
  if (typeof lrc === 'string') fd.append('lyrics_lrc', new Blob([lrc], { type: 'text/plain' }), 'lyrics.lrc');
  if (cover) fd.append('cover', cover);
  fd.append('params', JSON.stringify(pickParams(params)));
  if (songId) fd.append('song_id', songId);
  fd.append('replace', replace ? 'true' : 'false');
  return fd;
}

/**
 * multipart для POST /api/import/inspect: {source: 'usdb'|'files'|'url', usdb_id?, url?, files?}.
 * Файл из выбранной папки уходит с путём от неё (webkitRelativePath) — сервер сохраняет раскладку.
 */
export function inspectForm({ source, usdb_id: usdbId, url, files = [] }) {
  const fd = new FormData();
  fd.append('source', source);
  if (source === 'usdb') fd.append('usdb_id', String(usdbId));
  if (source === 'url') fd.append('url', (url || '').trim());
  if (source === 'files') for (const file of files) fd.append('files', file, file.webkitRelativePath || file.name);
  return fd;
}

/** multipart для POST /api/jobs/import — поля из import-logic.js::importFields. */
export function importForm({ token, index, artist, title, audio, youtube_url: youtubeUrl, instrumental, replace }) {
  const fd = new FormData();
  fd.append('token', token);
  fd.append('index', String(index));
  fd.append('artist', artist);
  fd.append('title', title);
  if (audio) fd.append('audio', audio);
  if (youtubeUrl) fd.append('youtube_url', youtubeUrl);
  fd.append('instrumental', instrumental ? 'true' : 'false');
  fd.append('replace', replace ? 'true' : 'false');
  return fd;
}
