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

export async function request(method, url, body) {
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

export const api = {
  status: () => request('GET', '/api/status'),
  defaults: () => request('GET', '/api/defaults'),

  jobs: (limit = 50) => request('GET', `/api/jobs?limit=${limit}`),
  generate: (form) => request('POST', '/api/jobs/generate', form),
  instrumental: (songId, replace) => request('POST', '/api/jobs/instrumental', { song_id: songId, replace }),
  cancel: (id) => request('POST', `/api/jobs/${id}/cancel`),
  restart: (id) => request('POST', `/api/jobs/${id}/restart`),
  republish: (id) => request('POST', `/api/jobs/${id}/republish`),
  logStreamUrl: (id) => `/api/jobs/${id}/log/stream`,

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

  trash: () => request('GET', '/api/trash'),
  restore: (id) => request('POST', `/api/trash/${encodeURIComponent(id)}/restore`),

  output: () => request('GET', '/api/settings/output'),
  saveOutput: (body) => request('PUT', '/api/settings/output', body),
  testOutput: (body) => request('POST', '/api/settings/output/test', body),
};
