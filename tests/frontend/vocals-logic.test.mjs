// Переключатель «Вокал» (web/static/js/vocals-logic.js): когда играть минусовку, память выбора.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  vocalsState, NO_INSTRUMENTAL, PREPARING, readVocalsPref, saveVocalsPref, requestOutcome,
} from '../../web/static/js/vocals-logic.js';

function fakeStorage(init = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m };
}

test('тексты', () => {
  assert.equal(NO_INSTRUMENTAL, 'Нет минусовки');
  assert.equal(PREPARING, 'Минусовка готовится…');
});

test('есть минусовка: вокал выкл. — играет минусовка, вкл. — исходный трек', () => {
  const song = { audio: 'A - T.mp3', instrumental: 'A - T [Instrumental].mp3' };
  assert.deepEqual(vocalsState(song, false), { available: true, reason: '', useInstrumental: true });
  assert.deepEqual(vocalsState(song, true), { available: true, reason: '', useInstrumental: false });
});

test('нет минусовки (или звука) — переключатель неактивен, всегда исходный трек', () => {
  assert.deepEqual(vocalsState({ audio: 'a.mp3', instrumental: null }, false),
    { available: false, reason: NO_INSTRUMENTAL, useInstrumental: false });
  assert.deepEqual(vocalsState({ audio: null, instrumental: 'i.mp3' }, false),
    { available: false, reason: NO_INSTRUMENTAL, useInstrumental: false });
  assert.equal(vocalsState({}, true).available, false);
});

test('выбор помнится общим ключом audio.vocals: «0» — выкл., иначе вкл.', () => {
  const st = fakeStorage();
  globalThis.localStorage = st;
  try {
    assert.equal(readVocalsPref(), true);
    saveVocalsPref(false);
    assert.equal(st.m.get('audio.vocals'), '0');
    assert.equal(readVocalsPref(), false);
    saveVocalsPref(true);
    assert.equal(st.m.get('audio.vocals'), '1');
    assert.equal(readVocalsPref(), true);
  } finally {
    delete globalThis.localStorage;
  }
});

test('хранилище недоступно — вокал вкл., запись без ошибки', () => {
  globalThis.localStorage = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  try {
    assert.equal(readVocalsPref(), true);
    assert.doesNotThrow(() => saveVocalsPref(false));
  } finally {
    delete globalThis.localStorage;
  }
});

test('ответ на «Сделать минусовку»: 409 — уже готовится, прочее — ошибка', () => {
  assert.equal(requestOutcome({ status: 409, detail: 'Эта песня уже в очереди' }), 'pending');
  assert.equal(requestOutcome({ status: 400, detail: 'У песни нет аудиофайла' }), 'error');
  assert.equal(requestOutcome(new Error('сеть')), 'error');
});
