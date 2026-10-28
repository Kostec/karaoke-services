// Синтезатор нот (G02): синус с огибающей, без микрофона и без файлов.
// Им же играет «Мелодия нот» в «Прогоне» и редакторе (планировщик — melody.js), «пианино» редактора. AudioContext создаётся лениво — в жесте пользователя
// (клик «♪», клавиша), иначе браузер оставит его на паузе. Работает и по http.

export const TONE_MIN_MS = 150;
export const TONE_MAX_MS = 2000;
const ATTACK_S = 0.012;
const RELEASE_S = 0.06;
const DEFAULT_GAIN = 0.25;

/** Частота ноты UltraStar: pitch 0 — до первой октавы (261,63 Гц), 9 — ля 440 Гц. */
export function pitchHz(pitch) {
  return 440 * 2 ** ((Number(pitch) - 9) / 12);
}

/** Длительность звучания: длина ноты, но не короче 0,15 и не длиннее 2 с. */
export function toneMs(ms) {
  const v = Number(ms);
  if (!Number.isFinite(v)) return TONE_MIN_MS;
  return Math.min(TONE_MAX_MS, Math.max(TONE_MIN_MS, v));
}

const RU_NAMES = ['до', 'до♯', 'ре', 'ре♯', 'ми', 'фа', 'фа♯', 'соль', 'соль♯', 'ля', 'ля♯', 'си'];
const LATIN_NAMES = ['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B'];

/** Имя ноты для подсказки: pitch 9 → «ля 4 · A4» (pitch 0 — до первой октавы, C4). */
export function pitchName(pitch) {
  const p = Math.round(Number(pitch)) || 0;
  const k = ((p % 12) + 12) % 12;
  const oct = 4 + Math.floor(p / 12);
  return `${RU_NAMES[k]} ${oct} · ${LATIN_NAMES[k]}${oct}`;
}

let audioCtx = null;
const sounding = new Set(); // голоса, которые ещё могут звучать, — их глушит closeTone()

/** Общий AudioContext (создаётся при первом звуке); null — браузер без Web Audio. */
function context() {
  if (!audioCtx) {
    const Ctor = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!Ctor) return null;
    audioCtx = new Ctor();
  }
  if (audioCtx.state === 'suspended') audioCtx.resume?.().catch(() => {});
  return audioCtx;
}

/** Поддерживает ли браузер Web Audio. */
export function toneSupported() {
  return !!(globalThis.AudioContext || globalThis.webkitAudioContext);
}

function voice(ac, pitch, atS, ms, gain) {
  const dur = toneMs(ms) / 1000;
  const osc = ac.createOscillator();
  const amp = ac.createGain();
  osc.type = 'sine';
  osc.frequency.value = pitchHz(pitch);
  amp.gain.setValueAtTime(0, atS);
  amp.gain.linearRampToValueAtTime(gain, atS + ATTACK_S);
  amp.gain.setValueAtTime(gain, Math.max(atS + ATTACK_S, atS + dur - RELEASE_S));
  amp.gain.linearRampToValueAtTime(0, atS + dur);
  osc.connect(amp).connect(ac.destination);
  osc.start(atS);
  osc.stop(atS + dur + 0.02);
  const v = { osc, amp };
  sounding.add(v);
  osc.onended = () => sounding.delete(v);
  return v;
}

function silence(v, ac) {
  const { osc, amp } = v;
  sounding.delete(v);
  try {
    const t = ac.currentTime;
    amp.gain.cancelScheduledValues(t);
    amp.gain.setValueAtTime(amp.gain.value, t);
    amp.gain.linearRampToValueAtTime(0, t + 0.02);
    osc.stop(t + 0.03);
  } catch { /* уже закончил */ }
}

/** Сыграть ноту высотой pitch; возвращает stop(). Без Web Audio — пустой stop. */
export function playTone(pitch, ms, { gain = DEFAULT_GAIN } = {}) {
  const ac = context();
  if (!ac) return () => {};
  const v = voice(ac, pitch, ac.currentTime + 0.01, ms, gain);
  return () => silence(v, ac);
}

/**
 * Сыграть последовательность нот [{pitch, startMs, ms}], начиная с момента fromMs песни.
 * Ноты, закончившиеся раньше fromMs, пропускаются; идущая — звучит с остатка. Возвращает {stop()}.
 * rate — скорость проигрывания песни (0.5 — вдвое медленнее): время до старта и длительность делятся на неё.
 */
export function toneSequence(notes, fromMs = 0, { gain = DEFAULT_GAIN, rate = 1 } = {}) {
  const ac = context();
  if (!ac) return { stop() {} };
  const r = Number(rate) > 0 ? Number(rate) : 1;
  const t0 = ac.currentTime + 0.02;
  const voices = [];
  for (const x of notes) {
    const end = x.startMs + x.ms;
    if (end <= fromMs) continue;
    const at = t0 + Math.max(0, x.startMs - fromMs) / 1000 / r;
    voices.push(voice(ac, x.pitch, at, Math.max(40, end - Math.max(x.startMs, fromMs)) / r, gain));
  }
  return { stop() { voices.forEach((v) => silence(v, ac)); voices.length = 0; } };
}

/**
 * Освободить звуковой движок: заглушить всё звучащее и закрыть AudioContext.
 * Следующий звук создаст новый контекст. Без контекста — ничего не делает.
 */
export function closeTone() {
  const ac = audioCtx;
  audioCtx = null;
  if (!ac) { sounding.clear(); return; }
  for (const v of [...sounding]) silence(v, ac);
  sounding.clear();
  try { ac.close?.()?.catch?.(() => {}); } catch { /* уже закрыт */ }
}
