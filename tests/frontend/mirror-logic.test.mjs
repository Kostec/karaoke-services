import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mirrorError, runLabel, mirrorSummary, mirrorStatus, onlyInTarget, MIRROR_SELF, MIRROR_REVERSE, MIRROR_DUPLICATE,
} from '../../web/static/js/mirror-logic.js';

const mirrors = [{ id: 'm_1', from_target: 'local', to_target: 't_pi' }];

test('mirrorError: тексты — как у сервера', () => {
  assert.equal(MIRROR_SELF, 'Хранилище не может быть зеркалом самого себя');
  assert.equal(MIRROR_REVERSE, 'Обратное зеркало уже есть');
  assert.deepEqual(mirrorError('local', 'local', []), { field: 'to_target', text: MIRROR_SELF });
  assert.deepEqual(mirrorError('t_pi', 'local', mirrors), { field: 'to_target', text: MIRROR_REVERSE });
  assert.deepEqual(mirrorError('local', 't_pi', mirrors), { field: 'to_target', text: MIRROR_DUPLICATE });
  assert.equal(mirrorError('local', 't_yd', mirrors), null);
});

test('mirrorError: пустой выбор и своё же зеркало при правке', () => {
  assert.deepEqual(mirrorError('', 't_pi', []), { field: 'from_target', text: 'Выберите, откуда копировать' });
  assert.deepEqual(mirrorError('local', '', []), { field: 'to_target', text: 'Выберите, куда копировать' });
  assert.equal(mirrorError('t_pi', 'local', mirrors, 'm_1'), null);
});

test('runLabel: сегодня, вчера, иначе дата', () => {
  const now = new Date(2026, 9, 27, 18, 0);
  assert.equal(runLabel(new Date(2026, 9, 27, 14, 30).toISOString(), now), 'сегодня 14:30');
  assert.equal(runLabel(new Date(2026, 9, 26, 23, 10).toISOString(), now), 'вчера 23:10');
  assert.equal(runLabel(new Date(2026, 9, 3, 9, 5).toISOString(), now), '03.10 09:05');
  assert.equal(runLabel(null, now), '');
});

test('mirrorSummary: итог прошлого прогона', () => {
  const now = new Date(2026, 9, 27, 18, 0);
  const at = new Date(2026, 9, 27, 14, 30).toISOString();
  const m = { last_run_at: at, last_result: { added: 3, updated: 1, only_in_target: [{}, {}] } };
  assert.equal(mirrorSummary(m, now), 'Последний прогон: сегодня 14:30 — добавлено 3, обновлено 1, только в цели 2');
  assert.equal(mirrorSummary({ last_run_at: at, last_result: { ...m.last_result, error: 'нет связи' } }, now),
    'Последний прогон: сегодня 14:30 — ошибка: нет связи');
  assert.equal(mirrorSummary({ last_run_at: null, last_result: null }, now), 'Ещё не синхронизировалось');
});

test('mirrorStatus: удалено, ждёт хранилище, идёт, выключено', () => {
  assert.deepEqual(mirrorStatus({ missing: true, enabled: false }),
    { kind: 'err', text: 'Хранилище удалено из настроек — зеркало выключено' });
  assert.deepEqual(mirrorStatus({ enabled: true, waiting: 'Ждёт хранилище «Pi»', job: { state: 'queued' } }),
    { kind: 'warn', text: 'Ждёт хранилище «Pi»' });
  assert.deepEqual(mirrorStatus({ enabled: true, job: { state: 'running', stage: 'Сканирование «Pi»' } }),
    { kind: 'run', text: 'Синхронизация: Сканирование «Pi»' });
  assert.deepEqual(mirrorStatus({ enabled: true, job: { state: 'queued', stage: null } }),
    { kind: 'run', text: 'Синхронизация в очереди' });
  assert.deepEqual(mirrorStatus({ enabled: false }), { kind: 'off', text: 'Выключено — само не синхронизируется' });
  assert.equal(mirrorStatus({ enabled: true }), null);
});

test('onlyInTarget: подписи и исключение уже убранных', () => {
  const m = { last_result: { only_in_target: [
    { song_id: 's1', artist: 'Звери', title: 'Районы-кварталы' }, { song_id: 's2', artist: '', title: 'Без автора' }] } };
  assert.deepEqual(onlyInTarget(m).map((s) => s.label), ['Звери — Районы-кварталы', 'Без автора']);
  assert.deepEqual(onlyInTarget(m, new Set(['s1'])).map((s) => s.song_id), ['s2']);
  assert.deepEqual(onlyInTarget({ last_result: null }), []);
});
