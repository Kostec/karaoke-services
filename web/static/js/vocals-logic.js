// «Вокал» в редакторе нот и «Прогоне»: чистые правила без DOM. Выключенный вокал — играет минусовка
// ([Instrumental]) с той же секунды; у песни без минусовки всегда исходный трек. DOM — vocals.js.

export const NO_INSTRUMENTAL = 'Нет минусовки';
export const PREPARING = 'Минусовка готовится…';
export const LOAD_FAILED = 'Минусовка не загрузилась — играет исходный трек';
const PREF_KEY = 'audio.vocals'; // общий для редактора и «Прогона»

/**
 * Состояние переключателя: song — {audio, instrumental} (имена файлов или null), vocalsOn — выбор пользователя.
 * → {available, reason: '' | NO_INSTRUMENTAL, useInstrumental}.
 */
export function vocalsState(song, vocalsOn) {
  const available = !!(song?.audio && song?.instrumental);
  return { available, reason: available ? '' : NO_INSTRUMENTAL, useInstrumental: available && !vocalsOn };
}

/** Включён ли вокал по памяти браузера (по умолчанию — да). */
export function readVocalsPref() {
  try { return globalThis.localStorage?.getItem(PREF_KEY) !== '0'; } catch { return true; }
}

export function saveVocalsPref(on) {
  try { globalThis.localStorage?.setItem(PREF_KEY, on ? '1' : '0'); } catch { /* приватный режим */ }
}

/**
 * Ошибка постановки минусовки → 'pending' | 'error'. 'pending' (ждать, сразу перечитав карточку) — только
 * 409 «уже в очереди» и «Минусовка уже есть» (карточка устарела); прочие 409 («нет аудиофайла»…) — ошибка.
 */
export function requestOutcome(error) {
  if (error?.status !== 409) return 'error';
  const detail = String(error.detail ?? error.message ?? '');
  return /уже в очереди|уже есть/i.test(detail) ? 'pending' : 'error';
}
