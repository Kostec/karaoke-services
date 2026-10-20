// Раздел «Очередь»: опрос /api/jobs каждые 2 с (пока вкладка видна), живой лог через SSE.

import { api, JOB_ACTIVE as ACTIVE, JOB_FINAL as FINAL, STAGE_PUBLISH, canRepublish } from './api.js';
import { h, clear, runAction, fmtDate, fmtDuration, confirmDialog, toast, songName } from './ui.js';

const POLL_MS = 2000;
const LOG_MAX_LINES = 5000;

const TYPE_LABEL = { generate: 'Генерация', instrumental: 'Минусовка', publish: 'Выкладка' };
const STATE_LABEL = {
  queued: 'В очереди', running: 'Идёт', publishing: 'Выкладка',
  done: 'Готово', failed: 'Ошибка', cancelled: 'Отменено',
};
const STAGE_LABEL = { [STAGE_PUBLISH]: 'Выкладка' };
// eslint-disable-next-line no-control-regex
const ANSI_RE = /\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]/g;

let root, listEl, emptyEl, errEl, hooks;
const cards = new Map(); // id → {el, parts, job}
const logs = new Map(); // id → {source, pre}
let timer = null;
let loading = false;

export function mount(section, ctx) {
  root = section;
  hooks = ctx;
  errEl = h('div', { class: 'banner err', hidden: true });
  emptyEl = h('div', { class: 'card empty', hidden: true },
    h('p', {}, 'Заданий нет — добавьте песню'),
    h('a', { class: 'btn primary', href: '#new' }, 'Добавить песню'));
  listEl = h('div', { class: 'jobs' });
  root.append(
    h('div', { class: 'view-head' }, h('h2', {}, 'Очередь'),
      h('a', { class: 'btn primary', href: '#new' }, '+ Новая песня')),
    errEl, emptyEl, listEl);
}

export function show() {
  poll();
}

/** Уход из раздела: закрыть все живые логи (EventSource). */
export function hide() {
  for (const id of [...logs.keys()]) {
    closeLog(id);
    const card = cards.get(id);
    if (card) card.sig = '';
  }
}

export function startPolling() {
  const tick = () => {
    clearTimeout(timer);
    if (document.visibilityState === 'visible') {
      poll().finally(() => { timer = setTimeout(tick, POLL_MS); });
    }
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') tick();
    else clearTimeout(timer);
  });
  tick();
}

export async function poll() {
  if (loading) return;
  loading = true;
  try {
    const jobs = await api.jobs(50);
    errEl.hidden = true;
    render(jobs);
  } catch (e) {
    errEl.textContent = `Не удалось получить очередь: ${e.detail}`;
    errEl.hidden = false;
  } finally {
    loading = false;
  }
}

function render(jobs) {
  hooks.setQueueCount(jobs.filter((j) => ACTIVE.includes(j.state)).length);
  emptyEl.hidden = jobs.length > 0;
  const seen = new Set();
  let prev = null;
  for (const job of jobs) {
    seen.add(job.id);
    let card = cards.get(job.id);
    if (!card) {
      card = createCard(job);
      cards.set(job.id, card);
    }
    updateCard(card, job);
    // порядок как в ответе сервера (новые сверху)
    const want = prev ? prev.nextSibling : listEl.firstChild;
    if (want !== card.el) listEl.insertBefore(card.el, want);
    prev = card.el;
  }
  for (const [id, card] of cards) {
    if (!seen.has(id)) {
      closeLog(id);
      card.el.remove();
      cards.delete(id);
    }
  }
}

function createCard(job) {
  const p = {
    title: h('div', { class: 'job-title' }),
    state: h('span', { class: 'state' }),
    meta: h('div', { class: 'job-meta' }),
    bar: h('div'),
    stage: h('div', { class: 'small muted' }),
    error: h('div', { class: 'job-error', hidden: true }),
    actions: h('div', { class: 'actions' }),
    logBox: h('div', { hidden: true }),
  };
  p.progress = h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100' }, p.bar);
  const el = h('article', { class: 'card job', dataset: { id: job.id } },
    h('div', { class: 'job-head' }, p.title, p.state),
    p.meta, p.progress, p.stage, p.error, p.actions, p.logBox);
  return { el, parts: p, job: null, sig: '' };
}

function updateCard(card, job) {
  const p = card.parts;
  card.job = job;
  const cancelling = job.cancel_requested && ACTIVE.includes(job.state);
  p.title.textContent = `${TYPE_LABEL[job.type] || 'Задание'}: ${songName(job.artist, job.title)}`;
  p.state.textContent = cancelling ? 'Отменяется…' : (STATE_LABEL[job.state] || 'Неизвестно');
  p.state.className = `state ${job.state}`;

  const meta = [`№ ${job.id}`, `создано ${fmtDate(job.created_at)}`];
  if (job.started_at) meta.push(`${FINAL.includes(job.state) ? 'шло' : 'идёт'} ${fmtDuration(job.started_at, job.finished_at)}`);
  if (job.finished_at) meta.push(`завершено ${fmtDate(job.finished_at)}`);
  clear(p.meta).append(...meta.map((m) => h('span', {}, m)));

  const pct = job.state === 'done' ? 100 : Math.max(0, Math.min(100, Math.round(job.percent || 0)));
  const showBar = job.state !== 'queued' && job.state !== 'cancelled';
  p.progress.hidden = !showBar;
  p.bar.style.width = `${pct}%`;
  p.progress.setAttribute('aria-valuenow', String(pct));
  const stage = job.stage ? (STAGE_LABEL[job.stage] || job.stage) : '';
  const finished = FINAL.includes(job.state);
  p.progress.hidden = !showBar || (finished && job.state !== 'done');
  p.stage.textContent = !finished && showBar ? [stage, `${pct}%`].filter(Boolean).join(' · ')
    : (job.state === 'failed' && stage ? `Этап: ${stage}` : '');
  p.stage.hidden = !p.stage.textContent;

  p.error.hidden = !(job.state === 'failed' && job.error);
  p.error.textContent = job.error || '';

  // кнопки перестраиваются только при смене состояния — чтобы не сбивать нажатие
  const sig = `${job.state}|${job.stage}|${job.cancel_requested}|${logs.has(job.id)}`;
  if (sig === card.sig) return;
  card.sig = sig;
  const btns = [];
  const logOpen = logs.has(job.id);
  btns.push(h('button', { type: 'button', 'aria-expanded': String(logOpen), onclick: () => toggleLog(card) },
    logOpen ? 'Скрыть лог' : 'Лог'));
  if (ACTIVE.includes(job.state) && !job.cancel_requested) {
    btns.push(h('button', {
      type: 'button', class: 'danger',
      onclick: async (ev) => {
        if (job.state !== 'queued'
          && !(await confirmDialog(`Отменить идущее задание «${songName(job.artist, job.title)}»?`, 'Отменить задание', { danger: true }))) return;
        await runAction(ev.target, () => api.cancel(job.id), 'Задание отменяется');
        poll();
      },
    }, 'Отменить'));
  }
  if (canRepublish(job)) {
    btns.push(h('button', {
      type: 'button', class: 'primary',
      onclick: async (ev) => { await runAction(ev.target, () => api.republish(job.id), 'Выкладка поставлена в очередь'); poll(); },
    }, 'Выложить повторно'));
  }
  if (FINAL.includes(job.state)) {
    btns.push(h('button', {
      type: 'button',
      onclick: async (ev) => { await runAction(ev.target, () => api.restart(job.id), 'Задание поставлено в очередь заново'); poll(); },
    }, 'Перезапустить'));
  }
  clear(p.actions).append(...btns);
}

// ---------------------------------------------------------------- лог

function toggleLog(card) {
  const id = card.job.id;
  if (logs.has(id)) {
    closeLog(id);
  } else {
    openLog(card);
  }
  card.sig = '';
  updateCard(card, card.job);
}

function openLog(card) {
  const id = card.job.id;
  const pre = h('pre', { class: 'log', tabindex: '0', 'aria-label': 'Лог задания' });
  const note = h('div', { class: 'small muted' }, 'Подключение к логу…');
  const earlier = h('button', { type: 'button', hidden: true }, 'Показать начало лога');
  clear(card.parts.logBox).append(earlier, pre, note);
  card.parts.logBox.hidden = false;
  // Без from сервер шлёт последние 500 строк. Первое событие `start` — смещение (в байтах)
  // начала первой отданной строки; при переподключении сервер шлёт его снова — берём первое.
  const source = new EventSource(api.logStreamUrl(id));
  let lines = 0;
  let firstOffset = null;
  source.onopen = () => { note.textContent = 'Лог обновляется в реальном времени'; };
  source.addEventListener('start', (ev) => {
    if (firstOffset !== null) return;
    firstOffset = Number(ev.data) || 0;
    earlier.hidden = !(firstOffset > 0);
  });
  source.onmessage = (ev) => {
    const stick = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 24;
    pre.append(document.createTextNode(ev.data.replace(ANSI_RE, '') + '\n'));
    lines += 1;
    if (lines > LOG_MAX_LINES) { pre.firstChild?.remove(); lines -= 1; }
    if (stick) pre.scrollTop = pre.scrollHeight;
  };
  earlier.addEventListener('click', async () => {
    earlier.disabled = true;
    try {
      const bytes = await api.logFrom(id, 0);
      const head = new TextDecoder().decode(bytes.slice(0, firstOffset))
        .replace(/\r\n?/g, '\n').replace(ANSI_RE, '');
      pre.prepend(document.createTextNode(head.endsWith('\n') ? head : `${head}\n`));
      pre.scrollTop = 0;
      earlier.hidden = true;
    } catch (e) {
      toast(e.detail, 'err');
      earlier.disabled = false;
    }
  });
  source.addEventListener('end', (ev) => {
    source.close();
    note.textContent = `Задание завершено: ${(STATE_LABEL[ev.data] || 'состояние неизвестно').toLowerCase()}`;
    if (!lines) pre.textContent = 'Лог пуст.';
  });
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) note.textContent = 'Соединение с логом потеряно';
    else note.textContent = 'Переподключение к логу…';
  };
  logs.set(id, { source, pre });
}

function closeLog(id) {
  const l = logs.get(id);
  if (!l) return;
  l.source.close();
  logs.delete(id);
  const card = cards.get(id);
  if (card) {
    clear(card.parts.logBox);
    card.parts.logBox.hidden = true;
  }
}
