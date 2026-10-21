// Расчёты таймлайна редактора нот без DOM (координаты, масштаб, волна) — под node-тесты.

export const ZOOM_MIN = 4;
export const ZOOM_MAX = 48;

/** Подпись строки сетки: у «до» — «C4» (высота 0 в UltraStar — C4), у прочих — null. */
export function octaveLabel(pitch) {
  if (((pitch % 12) + 12) % 12 !== 0) return null;
  return `C${4 + Math.floor(pitch / 12)}`;
}

/** Масштаб (px на бит) в допустимых пределах. */
export function clampZoom(ppb) {
  return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, ppb));
}

/** Новая прокрутка при смене масштаба: бит в центре видимой области остаётся в центре. */
export function zoomScroll({ scrollLeft, width, ppb }, next) {
  const center = (scrollLeft + width / 2) / ppb;
  return Math.max(0, center * next - width / 2);
}

/** Куда попал указатель на ноте шириной width: 'left' | 'right' (тянуть край) | 'move'. */
export function hitZone(offsetX, width) {
  const edge = Math.min(10, width / 3);
  if (offsetX < edge) return 'left';
  if (offsetX > width - edge) return 'right';
  return 'move';
}

/** Пики громкости: максимум модуля по окнам binMs во всех каналах (Float32Array на окно). */
export function peaks(channels, sampleRate, binMs = 10) {
  const len = channels.length ? channels[0].length : 0;
  const bin = Math.max(1, Math.round((sampleRate * binMs) / 1000));
  const out = new Float32Array(Math.ceil(len / bin));
  for (const ch of channels) {
    for (let i = 0; i < len; i += 1) {
      const v = Math.abs(ch[i]);
      const k = (i / bin) | 0;
      if (v > out[k]) out[k] = v;
    }
  }
  return out;
}

/** Индекс ноты, звучащей на бите beat (порядок нот любой; при перекрытии — начавшаяся позже), или −1 в паузе. */
export function noteAt(notes, beat) {
  // список партии дуэта не обязан быть отсортирован по времени — проход целиком
  let at = -1;
  notes.forEach((x, i) => {
    if (beat >= x.start && beat < x.start + x.length && (at < 0 || x.start >= notes[at].start)) at = i;
  });
  return at;
}

const RULER_STEPS = [1000, 2000, 5000, 10000, 15000, 30000, 60000];

/** Шаг подписей линейки в мс, чтобы подписи стояли не теснее 60 px. */
export function rulerStep(pxPerSecond) {
  return RULER_STEPS.find((ms) => (pxPerSecond * ms) / 1000 >= 60) ?? RULER_STEPS[RULER_STEPS.length - 1];
}

/** Диапазон высот сетки: от низшей до высшей ноты с запасом pad (без нот — C4…C5). */
export function pitchRange(notes, pad = 4) {
  if (!notes.length) return { min: -pad, max: 12 + pad };
  let min = Infinity, max = -Infinity;
  for (const x of notes) {
    if (x.pitch < min) min = x.pitch;
    if (x.pitch > max) max = x.pitch;
  }
  return { min: min - pad, max: max + pad };
}

/** Прокрутка, при которой точка x видна: уже видна — прежняя, иначе x на четверти ширины. */
export function ensureVisible(x, scrollLeft, width) {
  if (x >= scrollLeft && x <= scrollLeft + width * 0.9) return scrollLeft;
  return Math.max(0, x - width / 4);
}

/** Бит состояния с #GAP fromGap → бит с тем же временем звучания при #GAP toGap (мс, BPM). */
export function rebaseBeat(beat, fromGap, toGap, bpm) {
  return beat + ((fromGap - toGap) * bpm * 4) / 60000;
}
