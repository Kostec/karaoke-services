// Воспроизведение: одна общая дорожка для «▶» в списке песен и правило «играет один плеер».

import { toast } from './ui.js';

let track = null; // общий Audio списка
let activeBtn = null;
let activeUrl = '';
const players = new Set(); // <audio>/<video> страницы песни

function setState(btn, playing) {
  if (!btn) return;
  btn.textContent = playing ? '⏸' : '▶';
  btn.classList.toggle('on', playing);
  btn.setAttribute('aria-pressed', String(playing));
  btn.title = playing ? 'Пауза' : 'Послушать';
  btn.setAttribute('aria-label', btn.title);
}

function reset() {
  setState(activeBtn, false);
}

function pauseOthers(except) {
  for (const p of [...players]) {
    if (!p.isConnected) { players.delete(p); continue; }
    if (p !== except && !p.paused) p.pause();
  }
  if (track && except !== track && !track.paused) track.pause();
}

function ensureTrack() {
  if (track) return track;
  track = new Audio();
  track.preload = 'none';
  track.addEventListener('ended', reset);
  track.addEventListener('pause', reset);
  track.addEventListener('play', () => { pauseOthers(track); setState(activeBtn, true); });
  track.addEventListener('error', () => {
    if (!track.getAttribute('src')) return;
    reset();
    toast('Не удалось воспроизвести песню', 'err');
  });
  return track;
}

/** «▶»/«⏸» в списке: та же песня — пауза/продолжение, другая — останавливает прежнюю. */
export function playToggle(button, url) {
  const t = ensureTrack();
  if (activeUrl === url && t.getAttribute('src')) {
    if (activeBtn !== button) { setState(activeBtn, false); activeBtn = button; }
    if (t.paused) t.play().catch(playFailed); else t.pause();
    return;
  }
  setState(activeBtn, false);
  activeBtn = button;
  activeUrl = url;
  t.src = url;
  setState(button, true);
  t.play().catch(playFailed);
}

function playFailed(e) {
  if (e?.name === 'AbortError') return; // переключили на другую песню
  reset();
  if (e?.name !== 'NotSupportedError') toast('Не удалось воспроизвести песню', 'err');
}

/** Кнопка списка перерисована: если её песня играет — показать «⏸» и следить за ней. */
export function adoptPlayButton(button, url) {
  if (track && activeUrl === url && !track.paused) {
    activeBtn = button;
    setState(button, true);
  } else {
    setState(button, false);
  }
}

/** Плеер страницы: его запуск ставит на паузу остальные плееры и общую дорожку. */
export function soloPlayback(mediaEl) {
  players.add(mediaEl);
  mediaEl.addEventListener('play', () => pauseOthers(mediaEl));
  return mediaEl;
}

/** Остановить все плееры страницы (уход со страницы песни). */
export function pausePlayers() {
  for (const p of players) if (!p.paused) p.pause();
}
