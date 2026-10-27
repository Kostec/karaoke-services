// «Прогон» (#play?id=<song_id>): звук песни, бегущая дорожка нот по высоте с линией «сейчас»,
// крупно текущая строка с подсветкой спетых слогов и следующая; пауза, −5/+5 с, полоса,
// «Мелодия нот» (синтезатор tone.js). Микрофона нет. Чистая логика — play-logic.js.

import { api } from './api.js';
import { h, clear } from './ui.js';
import { timeline, frameAt, playProblem, melodyNotes, melodySlice, laneY, fmtClock } from './play-logic.js';
import { toneSequence, toneSupported } from './tone.js';

const WINDOW_MS = 8000; // ширина дорожки во времени
const NOW_PCT = 30; // линия «сейчас» — 30 % от левого края
const STEP_MS = 5000;
const MELODY_AHEAD_MS = 4000; // синтезатор планируется порциями на столько вперёд
const MELODY_KEY = 'play.melody';
const UNPITCHED = new Set(['F', 'R', 'G']);

let root;
let songId = '';
let seq = 0;
let view = null; // собранный прогон: {audio, raf, melody…, teardown()}

export function mount(section) {
  root = section;
}

export function show(params) {
  const id = params?.get('id') || '';
  teardown();
  songId = id;
  load();
}

export function hide() {
  teardown();
  seq += 1;
  songId = '';
  if (root) clear(root);
  document.title = 'Караоке';
}

function teardown() {
  if (view) view.teardown();
  view = null;
}

function backLink(id) {
  return h('a', { class: 'back', href: id ? `#song?id=${encodeURIComponent(id)}` : '#songs' }, '← Назад');
}

async function load() {
  const my = ++seq;
  const id = songId;
  if (!id) {
    clear(root).append(backLink(''), h('div', { class: 'banner warn' }, 'Не выбрана песня для прогона.'));
    return;
  }
  document.title = 'Прогон · Караоке';
  clear(root).append(backLink(id), h('p', { class: 'muted' }, 'Загрузка…'));
  try {
    const [details, payload] = await Promise.all([api.songDetails(id), api.notes(id)]);
    if (my !== seq || id !== songId) return;
    const problem = playProblem(details.song, payload);
    if (problem) {
      clear(root).append(backLink(id), h('div', { class: 'banner warn', role: 'status' }, problem));
      return;
    }
    view = build(id, details, payload);
  } catch (e) {
    if (my !== seq || id !== songId) return;
    clear(root).append(backLink(id), h('div', { class: 'banner err', role: 'alert' },
      h('p', { class: 'banner-text' }, e.status === 404 ? 'Песня не найдена' : `Прогон недоступен: ${e.detail || e.message}`),
      e.status === 404 ? null : h('button', { type: 'button', onclick: () => load() }, 'Повторить')));
  }
}

function readMelody() {
  try { return localStorage.getItem(MELODY_KEY) === '1'; } catch { return false; }
}

function saveMelody(on) {
  try { localStorage.setItem(MELODY_KEY, on ? '1' : '0'); } catch { /* приватный режим */ }
}

function singerLabel(tl, v) {
  const name = v === 1 ? tl.singers.p1 : tl.singers.p2;
  return name ? `Певец ${v} · ${name}` : `Певец ${v}`;
}

// ---------------------------------------------------------------- дорожка нот

function buildLane(tl, player, totalMs) {
  const notes = [];
  const track = h('div', { class: 'pv-track' });
  track.style.width = `${(totalMs / WINDOW_MS) * 100}%`;
  track.style.left = `${NOW_PCT}%`;
  for (const line of tl.lines) {
    if (tl.duet && line.player !== player) continue;
    for (const s of line.syllables) {
      const el = h('i', { class: `pv-nt${player === 2 ? ' p2' : ''}${UNPITCHED.has(s.type) ? ' free' : ''}${s.type === '*' ? ' gold' : ''}` });
      el.style.left = `${(s.startMs / totalMs) * 100}%`;
      el.style.width = `${(Math.max(s.endMs - s.startMs, 1) / totalMs) * 100}%`;
      el.style.top = `${laneY(UNPITCHED.has(s.type) ? tl.pitchRange.min : s.pitch, tl.pitchRange)}%`;
      notes.push({ el, startMs: s.startMs });
      track.append(el);
    }
  }
  notes.sort((a, b) => a.startMs - b.startMs);
  const el = h('div', { class: `pv-lane${tl.duet ? ' half' : ''}` }, track,
    h('div', { class: 'pv-now' }),
    tl.duet ? h('span', { class: `pv-sg sg${player}` }, singerLabel(tl, player)) : null);
  let done = 0;
  return {
    el,
    update(ms) {
      track.style.transform = `translateX(${-(ms / totalMs) * 100}%)`;
      let k = done;
      while (k < notes.length && notes[k].startMs <= ms) k += 1;
      while (k > 0 && notes[k - 1].startMs > ms) k -= 1;
      for (let i = Math.min(k, done); i < Math.max(k, done); i += 1) notes[i].el.classList.toggle('done', i < k);
      done = k;
    },
  };
}

// ---------------------------------------------------------------- строки текста

function buildLyrics(tl, player, withWho) {
  const cur = h('div', { class: 'pv-cur' });
  const nx = h('div', { class: 'pv-nx' });
  const el = h('div', { class: `c${player}` },
    withWho ? h('div', { class: `pv-who sg${player}` }, (player === 1 ? tl.singers.p1 : tl.singers.p2) || `Певец ${player}`) : null,
    cur, nx);
  let shownLine;
  let shownNext;
  let spans = [];
  return {
    el,
    update(ms) {
      const f = frameAt(tl, ms, tl.duet ? player : null);
      if (f.current !== shownLine) {
        shownLine = f.current;
        spans = (f.current?.syllables || []).map((s) => h('span', { class: 'r' }, s.text));
        clear(cur).append(...spans);
        if (!spans.length) cur.textContent = ' ';
      }
      if (f.next !== shownNext) {
        shownNext = f.next;
        nx.textContent = f.next ? f.next.syllables.map((s) => s.text).join('').trim() : ' ';
      }
      spans.forEach((sp, k) => {
        const cls = k === f.syllable ? 'a' : k < f.sung ? 's' : 'r';
        if (sp.className !== cls) sp.className = cls;
        if (cls === 'a') sp.style.setProperty('--p', `${Math.round(f.progress * 100)}%`);
      });
    },
  };
}

// ---------------------------------------------------------------- экран

function build(id, details, payload) {
  const song = details.song;
  const tl = timeline(payload);
  const melodyAll = melodyNotes(tl);
  const players = tl.duet ? [1, 2] : [1];

  const audio = new Audio();
  audio.preload = 'auto';
  audio.src = api.audioUrl(id);
  let durationMs = 0;
  const laneTotal = Math.max(tl.endMs + WINDOW_MS, WINDOW_MS);

  // фон: размытый #BACKGROUND, иначе обложка
  const media = details.media || {};
  const bgUrl = media.background ? api.fileUrl(id, media.background) : (song.cover ? api.coverUrl(id) : null);
  const bg = h('div', { class: 'pv-bg', 'aria-hidden': 'true' });
  if (bgUrl) bg.style.backgroundImage = `url("${bgUrl}")`;

  const fsBtn = document.fullscreenEnabled
    ? h('button', { type: 'button', title: 'Во весь экран', 'aria-label': 'Во весь экран', onclick: () => toggleFullscreen() }, '⛶')
    : null;
  const top = h('div', { class: 'pv-top' },
    h('a', { class: 'pv-btn', href: `#song?id=${encodeURIComponent(id)}`, title: 'К странице песни' }, '← Назад'),
    h('div', { class: 'pv-tt' }, h('b', {}, song.title || song.txt_name), h('span', {}, song.artist || '')),
    fsBtn);

  const lanes = players.map((p) => buildLane(tl, p, laneTotal));
  const lyrics = players.map((p) => buildLyrics(tl, p, tl.duet));
  const lyr = h('div', { class: `pv-lyr${tl.duet ? ' duet' : ''}` }, ...lyrics.map((l) => l.el));

  const playBtn = h('button', { type: 'button', class: 'pv-big', 'aria-label': 'Играть', title: 'Играть (пробел)' }, '▶');
  const back5 = h('button', { type: 'button', class: 'pv-back', title: 'Назад на 5 с (←)' }, '−5 с');
  const fwd5 = h('button', { type: 'button', class: 'pv-fwd', title: 'Вперёд на 5 с (→)' }, '+5 с');
  const tmCur = h('span', { class: 'pv-tm' }, '0:00');
  const tmAll = h('span', { class: 'pv-tm' }, '0:00');
  const seek = h('input', { type: 'range', class: 'pv-seek', min: '0', max: String(Math.round(tl.endMs)), step: '100',
    value: '0', 'aria-label': 'Позиция в песне' });
  const canTone = toneSupported();
  const melodyBox = h('input', { type: 'checkbox', disabled: !canTone });
  melodyBox.checked = canTone && readMelody();
  const melodyLabel = h('label', { class: 'pv-tg', title: canTone ? null : 'Браузер не умеет синтезировать звук (нет Web Audio)' },
    melodyBox, h('span', { class: 'pv-tgl', 'aria-hidden': 'true' }), ' Мелодия нот');
  const errBox = h('div', { class: 'banner err', role: 'alert', hidden: true });
  const ctl = h('div', { class: 'pv-ctl' },
    h('div', { class: 'pv-row pv-main' }, playBtn, back5, fwd5, tmCur, seek, tmAll),
    h('div', { class: 'pv-row' }, melodyLabel,
      h('span', { class: 'small pv-hint' }, 'ноты звучат тем же синтезатором, что кнопка «♪» в редакторе')));

  const el = h('div', { class: 'pv' }, bg, top, ...lanes.map((l) => l.el), lyr, errBox, ctl);
  clear(root).append(el);
  document.title = `Прогон: ${song.artist ? `${song.artist} — ` : ''}${song.title || song.txt_name} · Караоке`;

  let raf = 0;
  let playing = false;
  let melodySeqs = [];
  let scheduledUntil = null;
  let seeking = false;

  const nowMs = () => audio.currentTime * 1000;

  function render(ms) {
    for (const l of lanes) l.update(ms);
    for (const l of lyrics) l.update(ms);
    tmCur.textContent = fmtClock(ms);
    if (!seeking) seek.value = String(Math.round(ms));
  }

  function melodyStop() {
    for (const s of melodySeqs) s.stop();
    melodySeqs = [];
    scheduledUntil = null;
  }

  function melodyTick(ms) {
    if (!playing || !melodyBox.checked) return;
    let chunk = null;
    if (scheduledUntil == null) chunk = melodySlice(melodyAll, ms, ms + MELODY_AHEAD_MS, true);
    else if (scheduledUntil - ms < MELODY_AHEAD_MS / 2) chunk = melodySlice(melodyAll, scheduledUntil, ms + MELODY_AHEAD_MS);
    if (!chunk) return;
    scheduledUntil = ms + MELODY_AHEAD_MS;
    if (chunk.length) melodySeqs.push(toneSequence(chunk, ms));
    if (melodySeqs.length > 8) melodySeqs.shift(); // давно отзвучавшие порции
  }

  function loop() {
    raf = 0;
    if (!playing) return;
    const ms = nowMs();
    render(ms);
    melodyTick(ms);
    raf = requestAnimationFrame(loop);
  }

  function setPlaying(on) {
    playing = on;
    playBtn.textContent = on ? '❚❚' : '▶';
    playBtn.setAttribute('aria-label', on ? 'Пауза' : 'Играть');
    playBtn.title = on ? 'Пауза (пробел)' : 'Играть (пробел)';
    if (on) {
      if (!raf) raf = requestAnimationFrame(loop);
    } else {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      melodyStop();
      render(nowMs());
    }
  }

  // AudioContext браузер разрешает только из жеста пользователя — будим его пустой последовательностью
  const wakeTone = () => { if (melodyBox.checked) toneSequence([], 0); };

  function togglePlay() {
    if (audio.paused) {
      wakeTone();
      errBox.hidden = true;
      audio.play().catch((e) => {
        if (e?.name === 'AbortError') return;
        showError(`Не удалось начать воспроизведение: ${e?.message || e}`);
      });
    } else {
      audio.pause();
    }
  }

  function seekTo(ms) {
    const max = durationMs || tl.endMs;
    const v = Math.max(0, Math.min(ms, max));
    audio.currentTime = v / 1000;
    melodyStop();
    render(v);
  }

  function showError(text) {
    errBox.textContent = text;
    errBox.hidden = false;
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    else el.requestFullscreen?.().catch(() => {});
  }

  function onKey(e) {
    if (root.hidden || e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = e.target?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
      if (!(tag === 'INPUT' && e.target.type === 'checkbox')) return;
    }
    if (e.code === 'Space') {
      if (tag === 'BUTTON' || tag === 'A') return; // кнопку пробел нажмёт сам
      e.preventDefault();
      togglePlay();
    } else if (e.code === 'ArrowLeft') {
      e.preventDefault();
      seekTo(nowMs() - STEP_MS);
    } else if (e.code === 'ArrowRight') {
      e.preventDefault();
      seekTo(nowMs() + STEP_MS);
    }
  }

  playBtn.addEventListener('click', togglePlay);
  back5.addEventListener('click', () => seekTo(nowMs() - STEP_MS));
  fwd5.addEventListener('click', () => seekTo(nowMs() + STEP_MS));
  seek.addEventListener('input', () => { seeking = true; render(Number(seek.value)); });
  seek.addEventListener('change', () => { seeking = false; seekTo(Number(seek.value)); });
  melodyBox.addEventListener('change', () => {
    saveMelody(melodyBox.checked);
    if (melodyBox.checked) wakeTone();
    else melodyStop();
  });
  audio.addEventListener('play', () => setPlaying(true));
  audio.addEventListener('pause', () => setPlaying(false));
  audio.addEventListener('ended', () => setPlaying(false));
  audio.addEventListener('seeked', () => { if (!playing) render(nowMs()); });
  audio.addEventListener('loadedmetadata', () => {
    durationMs = Number.isFinite(audio.duration) ? audio.duration * 1000 : 0;
    if (durationMs) {
      seek.max = String(Math.round(durationMs));
      tmAll.textContent = fmtClock(durationMs);
    }
  });
  audio.addEventListener('error', () => {
    if (!audio.getAttribute('src')) return; // освобождение в teardown
    setPlaying(false);
    showError('Не удалось загрузить звук песни: файл недоступен или его формат не поддерживается браузером.');
  });
  document.addEventListener('keydown', onKey);
  tmAll.textContent = fmtClock(tl.endMs);
  render(0);

  return {
    id,
    teardown() {
      document.removeEventListener('keydown', onKey);
      playing = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      melodyStop();
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      if (document.fullscreenElement === el) document.exitFullscreen?.().catch(() => {});
    },
  };
}
