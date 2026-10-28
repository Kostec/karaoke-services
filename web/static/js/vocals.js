// Переключатель «Вокал» (редактор нот, «Прогон»): выключенный вокал — тот же <audio> играет минусовку
// с той же секунды. У песни без минусовки — «Нет минусовки» и «Сделать минусовку» (задание instrumental).
// Чистые правила — vocals-logic.js.

import { api, errorText } from './api.js';
import { h, toast as pageToast } from './ui.js';
import { watchJob } from './song-actions.js';
import {
  vocalsState, readVocalsPref, saveVocalsPref, requestOutcome, PREPARING,
} from './vocals-logic.js';

const POLL_MS = 5000;

/**
 * Сменить источник звука, сохранив позицию, скорость и «играет/пауза».
 * Resolve — источник готов (и снова играет, если играл); reject — новый файл не загрузился.
 * opts {at (с), rate, playing} — взять эти значения вместо текущих (возврат после сбоя минусовки).
 */
export function switchSource(audio, url, opts = {}) {
  const at = opts.at ?? (audio.currentTime || 0);
  const rate = opts.rate ?? (audio.playbackRate || 1);
  const wasPlaying = opts.playing ?? (!audio.paused && !audio.ended);
  return new Promise((resolve, reject) => {
    const done = () => {
      audio.removeEventListener('loadedmetadata', onMeta);
      audio.removeEventListener('error', onError);
    };
    function onMeta() {
      done();
      try { audio.currentTime = at; } catch { /* позиция за концом файла */ }
      audio.playbackRate = rate; // загрузка сбрасывает скорость к defaultPlaybackRate
      if (!wasPlaying) { resolve(); return; }
      audio.play().then(() => resolve(), (e) => (e?.name === 'AbortError' ? resolve() : reject(e)));
    }
    function onError() {
      done();
      reject(new Error('файл не загрузился'));
    }
    audio.addEventListener('loadedmetadata', onMeta);
    audio.addEventListener('error', onError);
    audio.src = url;
  });
}

/**
 * Переключатель «Вокал».
 * opts: {songId, audio (есть ли у песни звук), instrumental (имя файла или null), variant: 'play'|'editor',
 *        onChange(useInstrumental), onReady(instrumentalName), toast(text, kind)?}
 * onChange — играть минусовку (true) или исходный трек (false); onReady — минусовка появилась (до onChange).
 * → {el, set(on), toggle(), revert(), setInstrumental(name), dispose(), get vocals(), get available(),
 *    get useInstrumental()}; revert() — минусовка не загрузилась: показать «Вокал вкл.», выбор не меняя.
 */
export function createVocalsToggle({
  songId, audio = true, instrumental = null, variant = 'play', onChange, onReady, toast = pageToast,
}) {
  let inst = instrumental || null;
  let vocals = readVocalsPref();
  let preparing = false;
  let disposed = false;
  let pollTimer = 0;

  const box = h('input', { type: 'checkbox' });
  const label = variant === 'editor'
    ? h('label', { class: 'check', title: 'Вокал: выключен — играет минусовка (V)' }, box, ' Вокал')
    : h('label', { class: 'pv-tg', title: 'Вокал: выключен — играет минусовка (V)' },
      box, h('span', { class: 'pv-tgl', 'aria-hidden': 'true' }), ' Вокал');
  const note = h('span', { class: `small vocals-note${variant === 'play' ? '' : ' muted'}`, role: 'status' });
  const makeBtn = h('button', { type: 'button', class: 'vocals-make', title: 'Поставить в очередь задание «Минусовка»' },
    'Сделать минусовку');
  const el = h('span', { class: `vocals-tg ${variant}` }, label, note, makeBtn);
  // в «Прогоне» части переключателя — прямо в ряду .pv-row (его стили — в app.css, редактора — в editors.css)
  if (variant === 'play') el.style.display = 'contents';

  const st = () => vocalsState({ audio, instrumental: inst }, vocals);

  function paint() {
    const s = st();
    box.disabled = !s.available;
    box.checked = s.available ? vocals : true;
    label.classList.toggle('off', !s.available);
    note.hidden = s.available;
    note.textContent = preparing ? PREPARING : s.reason;
    makeBtn.hidden = s.available || preparing || !audio;
  }

  /** Вокал вкл./выкл. (V, клик); у песни без минусовки — ничего. */
  function set(on) {
    if (!st().available) return;
    const before = st().useInstrumental;
    vocals = !!on;
    saveVocalsPref(vocals);
    paint();
    const now = st().useInstrumental;
    if (now !== before) onChange?.(now);
  }

  function setInstrumental(name) {
    const before = st().useInstrumental;
    inst = name || null;
    if (inst) preparing = false;
    paint();
    const now = st().useInstrumental;
    if (now !== before) onChange?.(now);
  }

  function ready(name) {
    if (disposed) return;
    clearTimeout(pollTimer);
    onReady?.(name);
    setInstrumental(name);
    toast('Минусовка готова — вокал можно выключить');
  }

  // карточка песни раз в 5 с, пока в ней не появится минусовка
  function poll(delay = POLL_MS) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      if (disposed) return;
      try {
        const song = await api.song(songId);
        if (disposed) return;
        if (song?.instrumental) { ready(song.instrumental); return; }
      } catch { /* сеть — попробуем позже */ }
      poll();
    }, delay);
  }

  function stopPreparing() {
    preparing = false;
    clearTimeout(pollTimer);
    paint();
  }

  async function make() {
    if (preparing || disposed) return;
    makeBtn.disabled = true;
    try {
      const job = await api.instrumental(songId, false);
      preparing = true;
      paint();
      watchJob(job, (j) => {
        if (disposed || !preparing) return;
        if (j.state === 'done') { poll(0); return; }
        stopPreparing();
        if (j.state === 'failed') toast(`Минусовка не получилась: ${j.error || 'ошибка задания'}`, 'err');
        else toast('Задание «Минусовка» отменено', 'err');
      });
    } catch (e) {
      if (requestOutcome(e) === 'pending') {
        preparing = true;
        paint();
        poll(0);
      } else {
        toast(`Не удалось поставить минусовку: ${errorText(e)}`, 'err');
      }
    } finally {
      makeBtn.disabled = false;
    }
  }

  box.addEventListener('change', () => set(box.checked));
  makeBtn.addEventListener('click', make);
  paint();

  return {
    el,
    set,
    toggle() { set(!vocals); },
    revert() {
      if (!st().available) return;
      vocals = true; // только на экране: в памяти браузера остаётся выбор пользователя
      paint();
    },
    setInstrumental,
    dispose() { disposed = true; clearTimeout(pollTimer); },
    get vocals() { return vocals; },
    get available() { return st().available; },
    /** Играть ли сейчас минусовку (по выбору и наличию). */
    get useInstrumental() { return st().useInstrumental; },
  };
}
