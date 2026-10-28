// Пульт Rii i8 (web/static/js/remote-logic.js): выбор соседа по геометрии и разбор клавиши в команду.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pickNeighbor, keyCommand, GLOBAL_KEYS } from '../../web/static/js/remote-logic.js';

const r = (left, top, width = 100, height = 30) => ({ left, top, right: left + width, bottom: top + height, width, height });

// Сетка, как на «Песнях»: ссылка карточки слева, ▶ справа, ниже — следующая карточка.
//   link1 (0,0)      play1 (300,0)
//   link2 (0,100)    play2 (300,100)
const grid = [
  { id: 'link1', rect: r(0, 0) },
  { id: 'play1', rect: r(300, 0, 40) },
  { id: 'link2', rect: r(0, 100) },
  { id: 'play2', rect: r(300, 100, 40) },
];

test('pickNeighbor: вниз — следующая карточка, вправо — её кнопка', () => {
  assert.equal(pickNeighbor(grid[0].rect, 'down', grid), 'link2');
  assert.equal(pickNeighbor(grid[0].rect, 'right', grid), 'play1');
});

test('pickNeighbor: вверх и влево', () => {
  assert.equal(pickNeighbor(grid[3].rect, 'up', grid), 'play1');
  assert.equal(pickNeighbor(grid[3].rect, 'left', grid), 'link2');
});

test('pickNeighbor: нет соседа в эту сторону → null', () => {
  assert.equal(pickNeighbor(grid[0].rect, 'up', grid), null);
  assert.equal(pickNeighbor(grid[0].rect, 'left', grid), null);
  assert.equal(pickNeighbor(grid[3].rect, 'down', grid), null);
  assert.equal(pickNeighbor(grid[3].rect, 'right', grid), null);
  assert.equal(pickNeighbor(r(0, 0), 'down', []), null);
});

test('pickNeighbor: смещение поперёк весит вдвое больше расстояния по оси', () => {
  // A: ниже на 100 и прямо под; B: ниже на 40, но сдвинут вбок на 200 → 40 + 2·200 > 100.
  const from = r(0, 0);
  const cands = [{ id: 'B', rect: r(200, 70) }, { id: 'A', rect: r(0, 130) }];
  assert.equal(pickNeighbor(from, 'down', cands), 'A');
  // Сдвиг вбок мал (20): 40 + 2·20 = 80 < 100 → B.
  const near = [{ id: 'B', rect: r(20, 70) }, { id: 'A', rect: r(0, 130) }];
  assert.equal(pickNeighbor(from, 'down', near), 'B');
});

test('pickNeighbor: без фокуса — первый сверху-слева', () => {
  const cands = [{ id: 'c', rect: r(300, 100) }, { id: 'b', rect: r(300, 20) }, { id: 'a', rect: r(10, 20) }];
  assert.equal(pickNeighbor(null, 'down', cands), 'a');
  assert.equal(pickNeighbor(null, 'up', cands), 'a');
  assert.equal(pickNeighbor(null, 'right', []), null);
});

// ---------------------------------------------------------------- keyCommand

const key = (k, extra = {}) => ({ key: k, code: '', ctrlKey: false, altKey: false, metaKey: false, shiftKey: false, ...extra });
const plain = { inText: false, inMultiline: false, inSelect: false, view: 'songs' };
const onSong = { ...plain, view: 'song' };
const inText = { ...plain, inText: true };
const inArea = { ...plain, inMultiline: true };
const inSelect = { ...plain, inSelect: true };

test('keyCommand: стрелки вне полей — переход', () => {
  assert.deepEqual(keyCommand(key('ArrowUp'), plain), { type: 'move', dir: 'up' });
  assert.deepEqual(keyCommand(key('ArrowDown'), plain), { type: 'move', dir: 'down' });
  assert.deepEqual(keyCommand(key('ArrowLeft'), plain), { type: 'move', dir: 'left' });
  assert.deepEqual(keyCommand(key('ArrowRight'), plain), { type: 'move', dir: 'right' });
});

test('keyCommand: в текстовом поле ←/→ — курсор, ↑/↓ — выход из поля', () => {
  assert.equal(keyCommand(key('ArrowLeft'), inText), null);
  assert.equal(keyCommand(key('ArrowRight'), inText), null);
  assert.deepEqual(keyCommand(key('ArrowUp'), inText), { type: 'move', dir: 'up' });
  assert.deepEqual(keyCommand(key('ArrowDown'), inText), { type: 'move', dir: 'down' });
});

test('keyCommand: многострочное поле и список — стрелки остаются полю', () => {
  for (const ctx of [inArea, inSelect]) {
    for (const k of ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']) assert.equal(keyCommand(key(k), ctx), null);
  }
});

test('keyCommand: Esc в поле — снять фокус', () => {
  for (const ctx of [inText, inArea, inSelect]) assert.deepEqual(keyCommand(key('Escape'), ctx), { type: 'blur' });
});

test('keyCommand: Ctrl/Alt/Meta пропускаются', () => {
  for (const mod of ['ctrlKey', 'altKey', 'metaKey']) {
    assert.equal(keyCommand(key('ArrowDown', { [mod]: true }), plain), null);
    assert.equal(keyCommand(key('1', { code: 'Digit1', [mod]: true }), plain), null);
    assert.equal(keyCommand(key('Escape', { [mod]: true }), onSong), null);
  }
});

test('keyCommand: цифры 1–5 — вкладки, вне полей', () => {
  for (let i = 1; i <= 5; i++) {
    assert.deepEqual(keyCommand(key(String(i), { code: `Digit${i}` }), plain), { type: 'tab', index: i - 1 });
  }
  assert.deepEqual(keyCommand(key('3', { code: 'Numpad3' }), plain), { type: 'tab', index: 2 });
  assert.equal(keyCommand(key('6', { code: 'Digit6' }), plain), null);
  assert.equal(keyCommand(key('1', { code: 'Digit1' }), inText), null);
  assert.equal(keyCommand(key('!', { code: 'Digit1', shiftKey: true }), plain), null);
});

test('keyCommand: + — новая песня, / — поиск', () => {
  assert.deepEqual(keyCommand(key('+', { code: 'Equal', shiftKey: true }), plain), { type: 'new' });
  assert.deepEqual(keyCommand(key('+', { code: 'NumpadAdd' }), plain), { type: 'new' });
  assert.deepEqual(keyCommand(key('/', { code: 'Slash' }), plain), { type: 'search' });
  assert.deepEqual(keyCommand(key('/', { code: 'NumpadDivide' }), plain), { type: 'search' });
  assert.equal(keyCommand(key('+', { code: 'NumpadAdd' }), inText), null);
  assert.equal(keyCommand(key('/', { code: 'Slash' }), inText), null);
});

test('keyCommand: ? и F1 — подсказка', () => {
  assert.deepEqual(keyCommand(key('?', { code: 'Slash', shiftKey: true }), plain), { type: 'help' });
  assert.deepEqual(keyCommand(key('F1', { code: 'F1' }), plain), { type: 'help' });
  assert.deepEqual(keyCommand(key('F1', { code: 'F1' }), inText), { type: 'help' });
  assert.equal(keyCommand(key('?', { code: 'Slash', shiftKey: true }), inText), null);
});

test('keyCommand: Esc/Backspace — назад только с не-вкладок', () => {
  assert.deepEqual(keyCommand(key('Escape'), onSong), { type: 'back' });
  assert.deepEqual(keyCommand(key('Backspace'), onSong), { type: 'back' });
  for (const view of ['check', 'new', 'play']) {
    assert.deepEqual(keyCommand(key('Backspace'), { ...plain, view }), { type: 'back' });
  }
  for (const view of ['queue', 'import', 'songs', 'trash', 'settings']) {
    assert.equal(keyCommand(key('Escape'), { ...plain, view }), null);
    assert.equal(keyCommand(key('Backspace'), { ...plain, view }), null);
  }
  assert.equal(keyCommand(key('Backspace'), { ...onSong, inText: true }), null);
});

test('keyCommand: прочие клавиши — null', () => {
  assert.equal(keyCommand(key('Enter'), plain), null);
  assert.equal(keyCommand(key('a', { code: 'KeyA' }), plain), null);
  assert.equal(keyCommand(key('Tab'), plain), null);
});

test('GLOBAL_KEYS: список [[клавиши], описание] с нужными клавишами', () => {
  assert.ok(Array.isArray(GLOBAL_KEYS) && GLOBAL_KEYS.length > 0);
  for (const [keys, text] of GLOBAL_KEYS) {
    assert.ok(Array.isArray(keys) && keys.length > 0);
    assert.equal(typeof text, 'string');
  }
  const all = GLOBAL_KEYS.flatMap(([keys]) => keys).join(' ');
  for (const k of ['↑', 'Enter', 'Esc', 'Backspace', '1', '+', '/', '?', 'F1']) assert.ok(all.includes(k), k);
});
