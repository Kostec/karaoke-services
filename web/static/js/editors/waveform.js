// Волна громкости трека для редактора нот (спека §8): fetch → decodeAudioData → пики по 10 мс.
// Рисуется только видимая часть — canvas шириной с область прокрутки.

import { peaks } from './timeline-math.js';

export const WAVE_MAX_BYTES = 60 * 1024 * 1024;
export const WAVE_BIN_MS = 10;

/** Пики громкости аудио по адресу url → {peaks: Float32Array, binMs}; ошибка — Error с русским текстом. */
function aborted(signal) {
  if (signal?.aborted) throw new DOMException('Отменено', 'AbortError');
}

/** Пауза, которую прерывает signal. */
function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('Отменено', 'AbortError')); }, { once: true });
  });
}

export async function loadPeaks(url, { signal } = {}) {
  let res;
  // 503 — файл на шаре занят (его же сейчас читает <audio>): пробуем ещё пару раз
  for (let attempt = 0; ; attempt += 1) {
    res = await fetch(url, { signal, credentials: 'same-origin' });
    aborted(signal);
    if (res.status !== 503 || attempt >= 3) break;
    await res.body?.cancel?.();
    await sleep(1500, signal);
  }
  if (!res.ok) throw new Error(`аудио не загрузилось (HTTP ${res.status})`);
  const size = Number(res.headers.get('content-length')) || 0;
  if (size > WAVE_MAX_BYTES) {
    res.body?.cancel?.();
    throw new Error('файл больше 60 МБ');
  }
  let buf = await res.arrayBuffer();
  aborted(signal);
  if (buf.byteLength > WAVE_MAX_BYTES) throw new Error('файл больше 60 МБ');
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) throw new Error('браузер не умеет разбирать аудио');
  const ctx = new Ctx();
  try {
    const audio = await ctx.decodeAudioData(buf);
    buf = null; // буфер файла больше не нужен
    aborted(signal);
    const chans = [];
    for (let c = 0; c < audio.numberOfChannels; c += 1) chans.push(audio.getChannelData(c));
    return { peaks: peaks(chans, audio.sampleRate, WAVE_BIN_MS), binMs: WAVE_BIN_MS };
  } finally {
    ctx.close?.();
  }
}

/**
 * Нарисовать видимую часть волны: canvas шириной width, левый край — scrollLeft (px таймлайна).
 * xToMs(x) — время в мс для x таймлайна.
 */
export function drawWave(canvas, wave, { scrollLeft, width, height, xToMs, color }) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(width));
  if (canvas.width !== w * dpr || canvas.height !== height * dpr) {
    canvas.width = w * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${height}px`;
  }
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, height);
  if (!wave) return;
  g.fillStyle = color;
  const mid = height / 2;
  const { peaks: p, binMs } = wave;
  for (let x = 0; x < w; x += 2) {
    const a = Math.floor(xToMs(scrollLeft + x) / binMs);
    const b = Math.max(a + 1, Math.floor(xToMs(scrollLeft + x + 2) / binMs));
    let v = 0;
    for (let k = Math.max(0, a); k < b && k < p.length; k += 1) if (p[k] > v) v = p[k];
    const hgt = Math.max(1, v * (height - 4));
    g.fillRect(x, mid - hgt / 2, 1.5, hgt);
  }
}
