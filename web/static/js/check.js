// Раздел «Проверка библиотеки» (#check): выбор хранилищ, запуск, прогресс, находки с кнопками исправлений.
// Чистая логика — check-logic.js; сервер — /api/library/check (отчёт хранится, видно при входе).

import { api, JOB_ACTIVE } from './api.js';
import { h, clear, toast, confirmDialog, fmtDate, runAction } from './ui.js';
import { watchJob } from './song-actions.js';
import { openCoverDialog } from './artwork.js';
import {
  groupFindings, countLabel, fixButtons, fixCall, skippedLines, progressLine, checkedLine,
  FIXED_DONE,
} from './check-logic.js';

const POLL_MS = 2000;
const SHOWN_FIRST = 10; // сколько находок группы видно сразу, остальные — «показать все»

let root = null;
let els = {};
let targets = [];
let report = { findings: null };
let job = null; // идущая проверка
let picked = null; // Set id выбранных хранилищ (null — ещё не выбирали: все)
let timer = null;
let marks = new Map(); // id находки → подпись «Исправлено…» (для текущего отчёта)
let marksFor = '';
const expanded = new Set(); // виды, развёрнутые «показать все»

export function mount(section) {
  root = section;
  els = {
    banner: h('div', { class: 'banner err', hidden: true, role: 'alert' }),
    picks: h('div', { class: 'stores-pick' }),
    run: h('button', { type: 'button', class: 'primary', onclick: start }, 'Проверить'),
    last: h('span', { class: 'muted small' }),
    progress: h('div', { class: 'progress', hidden: true }, h('div')),
    stage: h('div', { class: 'small muted', hidden: true }),
    skipped: h('div'),
    result: h('div'),
  };
  els.card = h('div', { class: 'card check-card' }, els.picks,
    h('div', { class: 'actions check-actions' }, els.run, els.last), els.progress, els.stage, els.skipped);
  root.append(
    h('a', { class: 'back', href: '#songs' }, '← Песни'),
    h('h2', { class: 'h' }, 'Проверка библиотеки'),
    els.banner, els.card, els.result);
}

export async function show() {
  els.banner.hidden = true;
  try {
    const [t, r] = await Promise.all([api.targets(), api.libraryReport()]);
    targets = t.targets || [];
    apply(r);
  } catch (e) {
    els.banner.hidden = false;
    els.banner.textContent = e.detail || 'Не удалось загрузить проверку';
  }
}

export function hide() {
  clearTimeout(timer);
  timer = null;
}

function apply(r) {
  job = r.job && JOB_ACTIVE.includes(r.job.state) ? r.job : null;
  report = r;
  const stamp = r.finished_at || '';
  if (stamp !== marksFor) { marks = new Map(); marksFor = stamp; expanded.clear(); }
  render();
  clearTimeout(timer);
  timer = job ? setTimeout(poll, POLL_MS) : null;
}

async function poll() {
  try {
    apply(await api.libraryReport());
  } catch {
    timer = setTimeout(poll, POLL_MS); // сеть мигнула — пробуем снова
  }
}

async function start() {
  const ids = [...pickedSet()];
  if (!ids.length) { toast('Выберите хотя бы одно хранилище', 'err'); return; }
  const all = ids.length === targets.length;
  const res = await runAction(els.run, () => api.libraryCheck(all ? null : ids));
  if (res) apply(await api.libraryReport());
  else if (!job) show(); // 409 «уже идёт» — подхватим идущую
}

function pickedSet() {
  if (!picked) picked = new Set(targets.map((t) => t.id));
  return picked;
}

function renderPicks() {
  const set = pickedSet();
  clear(els.picks).append(...targets.map((t) => {
    const box = h('input', { type: 'checkbox', checked: set.has(t.id), disabled: !!job });
    box.addEventListener('change', () => { if (box.checked) set.add(t.id); else set.delete(t.id); });
    return h('label', { class: 'check' }, box, t.name || t.label || t.id);
  }));
}

function render() {
  renderPicks();
  els.run.disabled = !!job;
  els.run.textContent = job ? 'Проверяется…' : (Array.isArray(report.findings) ? 'Проверить снова' : 'Проверить');
  els.progress.hidden = els.stage.hidden = !job;
  if (job) {
    els.progress.firstChild.style.width = `${Math.max(0, Math.min(100, job.percent || 0))}%`;
    els.stage.textContent = progressLine(job);
  }
  els.last.textContent = checkedLine(report, fmtDate);
  clear(els.skipped).append(...skippedLines(report).map((t) => h('div', { class: 'banner warn' }, t)));
  renderResult();
}

function renderResult() {
  clear(els.result);
  if (!Array.isArray(report.findings)) {
    if (!job) {
      els.result.append(h('div', { class: 'card check-empty' }, h('p', { class: 'muted small' },
        'До первого запуска: проверка найдёт песни без звука и обложки, битые ссылки, кодировку, дубли и разошедшиеся копии.')));
    }
    return;
  }
  const groups = groupFindings(report);
  if (!groups.length) {
    if (!job) {
      els.result.append(h('div', { class: 'card check-empty' }, h('div', { class: 'check-ok' }, '✓'),
        h('p', {}, h('b', {}, 'Проблем не найдено')),
        h('p', { class: 'muted small' }, checkedLine(report, fmtDate).replace('Последняя проверка', 'Проверено'))));
    }
    return;
  }
  for (const g of groups) els.result.append(renderGroup(g));
}

function renderGroup(g) {
  const all = expanded.has(g.kind);
  const list = all ? g.findings : g.findings.slice(0, SHOWN_FIRST);
  const rest = g.findings.length - list.length;
  return h('details', { class: 'card grp', open: true },
    h('summary', {}, g.label, ' ', h('span', { class: 'n' }, countLabel(g.kind, g.count))),
    list.map(renderFinding),
    rest > 0 ? h('div', { class: 'find' }, h('div', { class: 'muted small' }, `…и ещё ${rest} `,
      h('a', { href: '#check', onclick: (e) => { e.preventDefault(); expanded.add(g.kind); renderResult(); } },
        'показать все'))) : null);
}

const targetLabel = (id) => {
  const t = targets.find((x) => x.id === id);
  return t?.name || t?.label || id;
};

function renderFinding(f) {
  const row = h('div', { class: 'find' });
  const mark = marks.get(f.id);
  const why = f.kind === 'encoding' && f.after
    ? h('div', { class: 'diff' }, h('s', {}, f.before), ' → ', h('b', {}, f.after))
    : null;
  const detail = f.kind === 'encoding' && f.after ? '' : f.detail;
  row.append(h('div', {},
    h('b', {}, `${f.artist} — ${f.title}`), ' ', h('span', { class: 'muted' }, `· ${targetLabel(f.target_id)}`),
    why, detail ? h('div', { class: 'why' }, detail) : null));
  if (mark) {
    row.classList.add('fixed');
    row.append(h('div', { class: 'fx' }, h('span', { class: `st${mark.err ? ' err' : ''}` }, mark.text)));
    return row;
  }
  row.append(h('div', { class: 'fx' }, fixButtons(f, targets).map((b) => {
    const btn = h('button', { type: 'button', class: `sm${b.danger ? ' danger' : ''}`, disabled: !!b.disabled,
      title: b.disabled || null }, b.label);
    btn.addEventListener('click', () => fix(btn, f, b.fix));
    return btn;
  })));
  return row;
}

function setMark(f, text, err = false) {
  marks.set(f.id, { text, err });
  renderResult();
}

async function fix(btn, f, fx) {
  const call = fixCall(fx, f);
  if (!call) return;
  if (call.method === 'cover') {
    await runAction(btn, async () => {
      const song = await api.song(f.song_id);
      openCoverDialog(song, { targets, currentTargetId: f.target_id, outputOk: true, reload: () => {} });
    });
    return;
  }
  if (call.confirm && !(await confirmDialog(call.confirm.text, call.confirm.ok, { danger: true }))) return;
  const res = await runAction(btn, () => api[call.method](...call.args));
  if (res === undefined) return;
  const failure = res?.errors?.[0]?.detail;
  if (failure) { toast(failure, 'err'); return; }
  if (call.method === 'copySongs' && !res.queued?.length) {
    toast('Копировать нечего: копия уже поставлена или совпадает', 'err');
    return;
  }
  setMark(f, call.mark);
  const watched = res?.id ? res : res?.queued?.length ? { id: res.queued[0] } : null;
  if (watched) {
    watchJob(watched, (j) => {
      if (j.state === 'done') setMark(f, FIXED_DONE);
      else {
        setMark(f, 'Не удалось исправить', true);
        toast(j.error || 'Исправление не удалось', 'err');
      }
    });
  }
}
