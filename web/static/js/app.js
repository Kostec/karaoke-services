// Точка входа: разделы по хэшу, шапка со статусом GPU и папки результата.

import { api } from './api.js';
import * as queue from './queue.js';
import * as newSong from './new-song.js';
import * as importView from './import.js';
import * as songs from './songs.js';
import * as trash from './trash.js';
import * as settings from './settings.js';
// Редакторы (таск 07): модуль вызывает registerSongEditor().
import './editors/index.js';

const VIEWS = { queue, new: newSong, import: importView, songs, trash, settings };
const STATUS_EVERY_MS = 15000;

let current = null;

function parseHash() {
  const raw = location.hash.replace(/^#/, '');
  const [name, query = ''] = raw.split('?');
  return { name: VIEWS[name] ? name : 'queue', params: new URLSearchParams(query) };
}

function route() {
  const { name, params } = parseHash();
  for (const s of document.querySelectorAll('main > section')) s.hidden = s.dataset.view !== name;
  for (const a of document.querySelectorAll('nav.tabs a')) {
    if (a.dataset.view === name) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  }
  if (current && current !== name) VIEWS[current].hide?.();
  current = name;
  VIEWS[name].show(params);
}

// ---------------------------------------------------------------- шапка

const gpuEl = document.getElementById('status-gpu');
const outEl = document.getElementById('status-output');

export function renderStatus(st) {
  const gpu = st.gpu || {};
  gpuEl.title = '';
  if (gpu.ok === true) {
    gpuEl.textContent = `GPU: ${gpu.name || 'доступен'} ✓`;
    gpuEl.className = 'ok';
  } else if (gpu.ok === false) {
    gpuEl.textContent = `GPU недоступен — генерация остановлена${gpu.error ? `: ${gpu.error}` : ''}`;
    gpuEl.className = 'bad';
  } else {
    gpuEl.textContent = gpu.error || 'Воркер ещё не сообщил статус GPU';
    gpuEl.className = 'muted';
  }
  const out = st.output || {};
  if (out.ok) {
    outEl.textContent = `Папка: ${out.label || ''} ✓`;
    outEl.className = 'ok';
  } else {
    outEl.textContent = out.error || `Папка результата недоступна: ${out.label || ''}`; // сервер уже пишет причину целиком
    outEl.className = 'bad';
  }
}

async function refreshStatus() {
  if (document.visibilityState !== 'visible') return;
  try {
    renderStatus(await api.status());
  } catch (e) {
    gpuEl.textContent = e.detail;
    gpuEl.className = 'bad';
  }
}

export function setQueueCount(n) {
  const el = document.getElementById('queue-count');
  el.hidden = !n;
  el.textContent = n ? String(n) : '';
  el.title = n ? 'Заданий в очереди и в работе' : '';
}

// ---------------------------------------------------------------- запуск

for (const [name, view] of Object.entries(VIEWS)) {
  view.mount(document.getElementById(`view-${name}`), { setQueueCount, refreshStatus });
}
window.addEventListener('hashchange', route);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') refreshStatus();
});
route();
queue.startPolling();
refreshStatus();
setInterval(refreshStatus, STATUS_EVERY_MS);
