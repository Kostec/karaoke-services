// Пульт Rii i8: чистая логика — выбор соседа по геометрии и разбор клавиши в команду.
// DOM — в remote.js; здесь только данные (тестируется node:test).

/** Вкладки по порядку цифр 1–5; с них «назад» ничего не делает. */
export const TAB_VIEWS = ['queue', 'import', 'songs', 'trash', 'settings'];

/** Общие клавиши для подсказки «Клавиши пульта»: [[клавиши], описание]. */
export const GLOBAL_KEYS = [
  [['↑', '↓', '←', '→'], 'Перейти к соседнему элементу'],
  [['Enter'], 'Нажать выбранное'],
  [['Esc', 'Backspace'], 'Назад: со страницы песни, «Прогона», «Проверки», «Новой песни»'],
  [['Esc'], 'В поле ввода — выйти из поля; в окне — закрыть его'],
  [['1', '2', '3', '4', '5'], 'Вкладки: Очередь, Импорт, Песни, Корзина, Настройки'],
  [['+'], 'Новая песня'],
  [['/'], 'Поиск песен'],
  [['?', 'F1'], 'Эта подсказка'],
];

const EDGE_EPS = 2; // пикселей: соседние элементы могут чуть перекрываться рамками

const center = (rc) => ({ x: (rc.left + rc.right) / 2, y: (rc.top + rc.bottom) / 2 });

/** Расстояние по оси и смещение поперёк для кандидата rc от from; null — не в той стороне. */
function measure(from, rc, dir, strict) {
  const a = center(from);
  const b = center(rc);
  const vertical = dir === 'up' || dir === 'down';
  const cross = vertical ? Math.abs(b.x - a.x) : Math.abs(b.y - a.y);
  let axis;
  if (strict) {
    // Кандидат целиком за краем элемента фокуса.
    if (dir === 'down') axis = rc.top - from.bottom;
    else if (dir === 'up') axis = from.top - rc.bottom;
    else if (dir === 'right') axis = rc.left - from.right;
    else axis = from.left - rc.right;
    if (axis < -EDGE_EPS) return null;
    axis = Math.max(0, axis);
  } else {
    // Запасной путь: центр кандидата дальше центра фокуса.
    if (dir === 'down') axis = b.y - a.y;
    else if (dir === 'up') axis = a.y - b.y;
    else if (dir === 'right') axis = b.x - a.x;
    else axis = a.x - b.x;
    if (axis <= 0) return null;
  }
  return axis + 2 * cross;
}

/**
 * Ближайший элемент в сторону dir: вес — расстояние по оси + 2 × смещение поперёк.
 * fromRect null (фокуса нет) — первый сверху-слева. → id | null
 */
export function pickNeighbor(fromRect, dir, candidates) {
  const list = candidates || [];
  if (!list.length) return null;
  if (!fromRect) {
    let best = null;
    for (const c of list) {
      if (!best || c.rect.top < best.rect.top - EDGE_EPS
        || (Math.abs(c.rect.top - best.rect.top) <= EDGE_EPS && c.rect.left < best.rect.left)) best = c;
    }
    return best.id;
  }
  for (const strict of [true, false]) {
    let best = null;
    let bestW = Infinity;
    for (const c of list) {
      const w = measure(fromRect, c.rect, dir, strict);
      if (w !== null && w < bestW) { best = c; bestW = w; }
    }
    if (best) return best.id;
  }
  return null;
}

const ARROWS = { ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' };

/**
 * Клавиша → команда пульта или null (клавиша не пульта или остаётся полю/браузеру).
 * ctx: {inText, inMultiline, inSelect, view}
 */
export function keyCommand(e, ctx) {
  if (e.ctrlKey || e.altKey || e.metaKey) return null;
  const { inText = false, inMultiline = false, inSelect = false, view = '' } = ctx || {};
  const inField = inText || inMultiline || inSelect;
  const dir = ARROWS[e.key];
  if (dir) {
    if (inMultiline || inSelect) return null;
    if (inText && (dir === 'left' || dir === 'right')) return null; // курсор в поле
    return { type: 'move', dir };
  }
  if (e.key === 'F1') return { type: 'help' };
  if (e.key === 'Escape') {
    if (inField) return { type: 'blur' };
    return TAB_VIEWS.includes(view) ? null : { type: 'back' };
  }
  if (inField) return null;
  if (e.key === 'Backspace') return TAB_VIEWS.includes(view) ? null : { type: 'back' };
  const digit = /^(?:Digit|Numpad)([1-9])$/.exec(e.code || '');
  if (!e.shiftKey && (digit || /^[1-9]$/.test(e.key))) {
    const n = Number(digit ? digit[1] : e.key);
    return n <= TAB_VIEWS.length ? { type: 'tab', index: n - 1 } : null;
  }
  if (e.key === '+' || e.code === 'NumpadAdd') return { type: 'new' };
  if (e.key === '?' || (e.code === 'Slash' && e.shiftKey)) return { type: 'help' };
  if (e.key === '/' || e.code === 'NumpadDivide' || (e.code === 'Slash' && !e.shiftKey)) return { type: 'search' };
  return null;
}
