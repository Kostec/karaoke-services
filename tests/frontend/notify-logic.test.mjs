// Уведомления браузера (notify-logic.js): можно ли их показывать и о чём сообщать.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  browserNotifyState, jobNotice, collectNotices, shouldShow, REASON_INSECURE,
} from '../../web/static/js/notify-logic.js';

const win = (secure, permission) => ({
  isSecureContext: secure,
  ...(permission === undefined ? {} : { Notification: { permission } }),
});

test('по http не с localhost — погашено с пояснением про Telegram', () => {
  const st = browserNotifyState(win(false, 'default'));
  assert.equal(st.ok, false);
  assert.equal(st.reason, 'Браузер разрешает уведомления только на localhost или https — используйте Telegram.');
  assert.equal(st.reason, REASON_INSECURE);
});

test('нет Notification или отказ — ok:false с причиной; иначе ok:true', () => {
  const none = browserNotifyState(win(true));
  assert.equal(none.ok, false);
  assert.match(none.reason, /Telegram/);
  const denied = browserNotifyState(win(true, 'denied'));
  assert.equal(denied.ok, false);
  assert.match(denied.reason, /запрещены/);
  assert.deepEqual(browserNotifyState(win(true, 'default')), { ok: true, reason: '', permission: 'default' });
  assert.deepEqual(browserNotifyState(win(true, 'granted')), { ok: true, reason: '', permission: 'granted' });
  assert.equal(browserNotifyState(null).ok, false);
});

const job = (state, extra = {}) => ({
  id: 7, type: 'generate', state, artist: 'Кино', title: 'Группа крови', error: null, ...extra,
});

test('уведомление только при переходе в done/failed', () => {
  assert.deepEqual(jobNotice(job('running'), job('done')),
    { title: '✅ Готово', body: 'Кино — Группа крови (генерация)' });
  assert.deepEqual(jobNotice(job('publishing'), job('failed', { error: 'ошибка выкладки: нет связи\nстрока лога' })),
    { title: '❌ Сбой', body: 'Кино — Группа крови (генерация) — ошибка выкладки: нет связи' });
  assert.equal(jobNotice(job('queued'), job('running')), null);
  assert.equal(jobNotice(job('done'), job('done')), null); // уже было
  assert.equal(jobNotice(job('running'), job('cancelled')), null);
  assert.equal(jobNotice(null, job('done')), null); // впервые увиденное — без уведомления
});

test('«готово» — только для заданий песни; «сбой» — для всех', () => {
  assert.equal(jobNotice(job('running', { type: 'copy' }), job('done', { type: 'copy' })), null);
  assert.equal(jobNotice(job('running', { type: 'publish' }), job('done', { type: 'publish' })), null);
  assert.equal(jobNotice(job('running', { type: 'copy' }), job('failed', { type: 'copy', error: 'нет связи' })).title,
    '❌ Сбой');
  for (const type of ['import', 'instrumental', 'video', 'artwork', 'audio', 'rename']) {
    assert.ok(jobNotice(job('running', { type }), job('done', { type })), type);
  }
});

test('опрос: первый — только запоминает, новое задание, успевшее закончиться, — уведомляет', () => {
  const first = collectNotices(null, [job('running'), job('done', { id: 6 })]);
  assert.deepEqual(first.notices, []);
  const second = collectNotices(first.seen, [
    job('done'), job('done', { id: 6 }), job('failed', { id: 9, error: 'сбой' }), job('queued', { id: 10 }),
  ]);
  assert.deepEqual(second.notices.map((n) => n.id), [7, 9]);
  const third = collectNotices(second.seen, [job('done'), job('failed', { id: 9 }), job('done', { id: 10 })]);
  assert.deepEqual(third.notices.map((n) => n.id), [10]);
});

test('показывать — только если включено, разрешено и вкладка не в фокусе', () => {
  const w = win(true, 'granted');
  assert.equal(shouldShow({ enabled: true, win: w, focused: false }), true);
  assert.equal(shouldShow({ enabled: true, win: w, focused: true }), false);
  assert.equal(shouldShow({ enabled: false, win: w, focused: false }), false);
  assert.equal(shouldShow({ enabled: true, win: win(true, 'default'), focused: false }), false);
  assert.equal(shouldShow({ enabled: true, win: win(false, 'granted'), focused: false }), false);
});
