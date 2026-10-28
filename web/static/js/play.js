// «Прогон» (#play?id=<song_id>): звук песни, бегущая дорожка нот по высоте с линией «сейчас»,
// крупно текущая строка с подсветкой спетых слогов и следующая; пауза, −5/+5 с, полоса,
// «Мелодия нот» (синтезатор tone.js, планировщик melody.js), «Вокал» (минусовка, vocals.js),
// клавиши пульта и медиаклавиши (Media Session). Микрофона нет. Чистая логика — play-logic.js.

import { api } from './api.js';
import { h, clear } from './ui.js';
import { timeline, frameAt, playProblem, melodyNotes, laneY, fmtClock, lineStarts, lineJump } from './play-logic.js';
import { toneSequence, toneSupported, closeTone } from './tone.js';
import { createMelody } from './melody.js';
import { createVocalsToggle, switchSource } from './vocals.js';
import { LOAD_FAILED, NO_INSTRUMENTAL } from './vocals-logic.js';
import { setScreenKeys, setMediaHandlers } from './remote.js';

const WINDOW_MS = 8000; // ширина дорожки во времени
const NOW_PCT = 30; // линия «сейчас» — 30 % от левого края
const STEP_MS = 5000;
const MELODY_KEY = 'play.melody';
const UNPITCHED = new Set(['F', 'R', 'G']);
/** Клавиши «Прогона» для подсказки пульта. */
const PLAY_KEYS = [
  [['Пробел', 'Enter', '⏯'], 'играть / пауза'],
  [['←', '→'], 'назад / вперёд на 5 с'],
  [['↑', '⏮'], 'к началу предыдущей строки'],
  [['↓', '⏭'], 'к началу следующей строки'],
  [['V'], 'вокал вкл. / выкл. (выкл. — играет минусовка)'],
  [['M'], 'мелодия нот вкл. / выкл.'],
  [['F'], 'во весь экран'],
  [['Esc'], 'к странице песни'],
  [['Tab'], 'к кнопкам и переключателям'],
];

let root;
let songId = '';
let seq = 0;
let view = null; // собранный прогон: {audio, raf, melody…, teardown()}

export function mount(section) {
  root = section;
  setScreenKeys('play', PLAY_KEYS);
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
  const starts = lineStarts(tl);
  const players = tl.duet ? [1, 2] : [1];
  const media = details.media || {};
  const origUrl = api.audioUrl(id);
  let instName = media.instrumental || song.instrumental || null;

  const audio = new Audio();
  audio.preload = 'auto';
  let durationMs = 0;
  const laneTotal = Math.max(tl.endMs + WINDOW_MS, WINDOW_MS);

  // фон: размытый #BACKGROUND, иначе обложка
  const bgUrl = media.background ? api.fileUrl(id, media.background) : (song.cover ? api.coverUrl(id) : null);
  const bg = h('div', { class: 'pv-bg', 'aria-hidden': 'true' });
  if (bgUrl) bg.style.backgroundImage = `url("${bgUrl}")`;

  const fsBtn = document.fullscreenEnabled
    ? h('button', { type: 'button', title: 'Во весь экран (F)', 'aria-label': 'Во весь экран', onclick: () => toggleFullscreen() }, '⛶')
    : null;
  const top = h('div', { class: 'pv-top' },
    h('a', { class: 'pv-btn', href: `#song?id=${encodeURIComponent(id)}`, title: 'К странице песни (Esc)' }, '← Назад'),
    h('div', { class: 'pv-tt' }, h('b', {}, song.title || song.txt_name), h('span', {}, song.artist || '')),
    h('button', { type: 'button', class: 'remote-help', title: 'Клавиши пульта (?)', 'aria-label': 'Клавиши пульта' }, '⌨'),
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
  const melodyLabel = h('label', { class: 'pv-tg', title: canTone ? 'Мелодия нот (M)' : 'Браузер не умеет синтезировать звук (нет Web Audio)' },
    melodyBox, h('span', { class: 'pv-tgl', 'aria-hidden': 'true' }), ' Мелодия нот');
  const vocals = createVocalsToggle({
    songId: id,
    audio: !!song.audio,
    instrumental: instName,
    variant: 'play',
    onReady: (name) => { instName = name; },
    onChange: (useInst) => applySource(useInst),
    toast: (text, kind) => notice(text, kind),
  });
  const errBox = h('div', { class: 'banner err', role: 'alert', hidden: true });
  // сообщения «Прогона» — внутри .pv: тост страницы в полноэкранном режиме не виден
  const noteBox = h('div', { class: 'banner warn pv-note', role: 'status', hidden: true });
  const ctl = h('div', { class: 'pv-ctl' },
    h('div', { class: 'pv-row pv-main' }, playBtn, back5, fwd5, tmCur, seek, tmAll),
    h('div', { class: 'pv-row' }, melodyLabel, vocals.el,
      h('span', { class: 'small pv-hint' }, 'ноты звучат тем же синтезатором, что кнопка «♪» в редакторе')));

  const el = h('div', { class: 'pv' }, bg, top, ...lanes.map((l) => l.el), lyr, errBox, noteBox, ctl);
  clear(root).append(el);
  document.title = `Прогон: ${song.artist ? `${song.artist} — ` : ''}${song.title || song.txt_name} · Караоке`;

  let raf = 0;
  let playing = false;
  let seeking = false;
  let dead = false;
  let srcInst = false; // играет минусовка
  let switching = false; // меняется источник звука — позиция <audio> пока не настоящая
  let switchSeq = 0;
  let lastMs = 0;
  const melody = createMelody({ notes: () => melodyAll });

  const nowMs = () => (switching ? lastMs : audio.currentTime * 1000);

  function render(ms) {
    lastMs = ms;
    for (const l of lanes) l.update(ms);
    for (const l of lyrics) l.update(ms);
    tmCur.textContent = fmtClock(ms);
    if (!seeking) seek.value = String(Math.round(ms));
  }

  function loop() {
    raf = 0;
    if (!playing) return;
    const ms = nowMs();
    render(ms);
    melody.tick(ms, playing && melodyBox.checked);
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
      melody.stop();
      render(nowMs());
    }
  }

  // AudioContext браузер разрешает только из жеста пользователя — будим его пустой последовательностью
  const wakeTone = () => { if (melodyBox.checked) toneSequence([], 0); };

  function startPlay() {
    wakeTone();
    errBox.hidden = true;
    audio.play().catch((e) => {
      if (e?.name === 'AbortError') return;
      showError(`Не удалось начать воспроизведение: ${e?.message || e}`);
    });
  }

  function togglePlay() {
    if (switching) return;
    if (audio.paused) startPlay();
    else audio.pause();
  }

  function seekTo(ms) {
    if (switching) return;
    const max = durationMs || tl.endMs;
    const v = Math.max(0, Math.min(ms, max));
    audio.currentTime = v / 1000;
    melody.stop();
    render(v);
  }

  /** ↑/↓, ⏮/⏭: к началу предыдущей / следующей строки (у дуэта — любой партии). */
  function jumpLine(dir) {
    const t = lineJump(starts, nowMs(), dir);
    if (t != null) seekTo(t);
  }

  /**
   * «Вокал»: тот же <audio> переходит на минусовку или исходный трек с той же секунды и в том же
   * состоянии; минусовка не загрузилась — тост и возврат к исходному.
   */
  async function applySource(useInst, { at = nowMs(), resume = playing || !audio.paused } = {}) {
    const my = ++switchSeq;
    lastMs = at;
    switching = true;
    if (!audio.paused) audio.pause();
    srcInst = !!useInst && !!instName;
    const url = srcInst ? api.fileUrl(id, instName) : origUrl;
    try {
      await switchSource(audio, url, { at: at / 1000, playing: false });
    } catch {
      if (my !== switchSeq || dead) return;
      switching = false;
      if (srcInst) {
        notice(LOAD_FAILED, 'err');
        vocals.revert();
        applySource(false, { at, resume });
      } else {
        setPlaying(false);
        showError('Не удалось загрузить звук песни: файл недоступен или его формат не поддерживается браузером.');
      }
      return;
    }
    if (my !== switchSeq || dead) return;
    switching = false;
    render(at);
    if (resume) startPlay();
  }

  function showError(text) {
    errBox.textContent = text;
    errBox.hidden = false;
  }

  let noteTimer = 0;
  /** Короткое сообщение внутри «Прогона» (видно и во весь экран); ошибка держится дольше. */
  function notice(text, kind = '') {
    clearTimeout(noteTimer);
    noteBox.className = `banner ${kind === 'err' ? 'err' : 'warn'} pv-note`;
    noteBox.textContent = text;
    noteBox.hidden = false;
    noteTimer = setTimeout(() => { noteBox.hidden = true; }, kind === 'err' ? 5000 : 3000);
  }

  function toggleFullscreen() {
    if (!document.fullscreenEnabled) return;
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    else el.requestFullscreen?.().catch(() => {});
  }

  function toggleMelody() {
    if (melodyBox.disabled) return;
    melodyBox.checked = !melodyBox.checked;
    melodyBox.dispatchEvent(new Event('change'));
  }

  function toggleVocals() {
    if (!vocals.available) { notice(NO_INSTRUMENTAL, 'err'); return; }
    vocals.toggle();
  }

  function onKey(e) {
    if (root.hidden || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    const tag = t?.tagName;
    const isCheck = tag === 'INPUT' && t.type === 'checkbox';
    if ((tag === 'INPUT' && !isCheck) || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (t?.closest?.('dialog')) return; // открыт диалог (подсказка пульта) — клавиши его
    const onButton = tag === 'BUTTON' || tag === 'A';
    const { code, key } = e;
    let act = null;
    if (code === 'Space') act = onButton ? null : togglePlay; // кнопку пробел нажмёт сам
    else if (code === 'Enter' || code === 'NumpadEnter') act = onButton || isCheck ? null : togglePlay;
    else if (key === 'MediaPlayPause' || code === 'MediaPlayPause') act = () => mediaKey(togglePlay);
    else if (code === 'ArrowLeft') act = () => seekTo(nowMs() - STEP_MS);
    else if (code === 'ArrowRight') act = () => seekTo(nowMs() + STEP_MS);
    else if (code === 'ArrowUp' || key === 'MediaTrackPrevious' || code === 'MediaTrackPrevious') act = () => jumpLine(-1);
    else if (code === 'ArrowDown' || key === 'MediaTrackNext' || code === 'MediaTrackNext') act = () => jumpLine(1);
    else if (code === 'KeyV' && !e.shiftKey) act = toggleVocals;
    else if (code === 'KeyM' && !e.shiftKey) act = toggleMelody;
    else if (code === 'KeyF' && !e.shiftKey) act = toggleFullscreen;
    else if (code === 'Escape') act = () => { location.hash = `#song?id=${encodeURIComponent(id)}`; };
    if (!act) return;
    e.preventDefault();
    act();
  }

  playBtn.addEventListener('click', togglePlay);
  back5.addEventListener('click', () => seekTo(nowMs() - STEP_MS));
  fwd5.addEventListener('click', () => seekTo(nowMs() + STEP_MS));
  seek.addEventListener('input', () => { seeking = true; render(Number(seek.value)); });
  seek.addEventListener('change', () => { seeking = false; seekTo(Number(seek.value)); });
  melodyBox.addEventListener('change', () => {
    saveMelody(melodyBox.checked);
    if (melodyBox.checked) wakeTone();
    else melody.stop();
  });
  audio.addEventListener('play', () => setPlaying(true));
  audio.addEventListener('pause', () => setPlaying(false));
  audio.addEventListener('ended', () => setPlaying(false));
  audio.addEventListener('seeked', () => { if (!playing && !switching) render(nowMs()); });
  audio.addEventListener('loadedmetadata', () => {
    durationMs = Number.isFinite(audio.duration) ? audio.duration * 1000 : 0;
    if (durationMs) {
      seek.max = String(Math.round(durationMs));
      tmAll.textContent = fmtClock(durationMs);
    }
  });
  audio.addEventListener('error', () => {
    if (!audio.getAttribute('src') || switching || dead) return; // освобождение в teardown, смена источника
    if (srcInst) { // минусовка оборвалась на ходу — к исходному треку
      notice(LOAD_FAILED, 'err');
      vocals.revert();
      applySource(false, { at: lastMs, resume: playing });
      return;
    }
    setPlaying(false);
    showError('Не удалось загрузить звук песни: файл недоступен или его формат не поддерживается браузером.');
  });
  document.addEventListener('keydown', onKey);
  // одна медиаклавиша может прийти дважды (keydown и Media Session) — второе нажатие в 0,4 с не считается
  let mediaAt = 0;
  function mediaKey(fn) {
    const t = performance.now();
    if (t - mediaAt < 400) return;
    mediaAt = t;
    fn();
  }
  setMediaHandlers({
    play: () => mediaKey(() => { if (audio.paused) togglePlay(); }),
    pause: () => mediaKey(() => { if (!audio.paused) togglePlay(); }),
    previoustrack: () => jumpLine(-1),
    nexttrack: () => jumpLine(1),
  });
  tmAll.textContent = fmtClock(tl.endMs);
  render(0);
  if (vocals.useInstrumental) applySource(true, { at: 0, resume: false });
  else audio.src = origUrl;

  return {
    id,
    teardown() {
      dead = true;
      document.removeEventListener('keydown', onKey);
      setMediaHandlers(null);
      vocals.dispose();
      clearTimeout(noteTimer);
      playing = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      melody.stop();
      closeTone();
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      if (document.fullscreenElement === el) document.exitFullscreen?.().catch(() => {});
    },
  };
}
