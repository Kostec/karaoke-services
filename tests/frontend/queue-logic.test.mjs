import test from 'node:test';
import assert from 'node:assert/strict';
import {
  nightStart, timeStart, startIso, scheduleLabel, queuedOrder, displayOrder, queuePlaces,
} from '../../web/static/js/queue-logic.js';

const at = (d, h, m = 0) => new Date(2026, 9, d, h, m);

test('nightStart: до часа ночи — сегодня, после — завтра, ровно 01:00 — завтра', () => {
  assert.deepEqual(nightStart(at(27, 0, 30)), at(27, 1));
  assert.deepEqual(nightStart(at(27, 14)), at(28, 1));
  assert.deepEqual(nightStart(at(27, 1, 0)), at(28, 1));
  assert.deepEqual(nightStart(at(31, 23)), new Date(2026, 10, 1, 1, 0));
});

test('timeStart: ближайшее время и отказ на мусоре', () => {
  assert.deepEqual(timeStart('22:30', at(27, 14)), at(27, 22, 30));
  assert.deepEqual(timeStart('09:00', at(27, 14)), at(28, 9));
  assert.equal(timeStart('', at(27, 14)), null);
  assert.equal(timeStart('25:00', at(27, 14)), null);
});

test('startIso: ISO с поясом Z, а не сырое локальное время', () => {
  for (const d of [nightStart(at(27, 14)), timeStart('22:30', at(27, 14))]) {
    const iso = startIso(d);
    assert.match(iso, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    assert.equal(new Date(iso).getTime(), d.getTime());
  }
});

test('scheduleLabel: сегодня, завтра, дата; не отложено — пусто', () => {
  const now = at(27, 14);
  const job = (d, extra = {}) => ({ state: 'queued', start_at: d.toISOString(), ...extra });
  assert.equal(scheduleLabel(job(at(27, 23)), now), 'Начнётся сегодня в 23:00');
  assert.equal(scheduleLabel(job(at(28, 1)), now), 'Начнётся завтра в 01:00');
  assert.equal(scheduleLabel(job(at(30, 9, 5)), now), 'Начнётся 30.10 в 09:05');
  assert.equal(scheduleLabel({ state: 'queued', start_at: null }, now), '');
  assert.equal(scheduleLabel(job(at(28, 1), { state: 'running' }), now), '');
});

test('порядок: position, у старых id; места только у неотложенных', () => {
  const jobs = [
    { id: 5, state: 'queued', position: 2 },
    { id: 6, state: 'queued', position: 1, start_at: '2026-10-28T01:00:00+00:00' },
    { id: 7, state: 'queued', position: null },
    { id: 4, state: 'running' },
    { id: 3, state: 'done' },
  ];
  assert.deepEqual(queuedOrder(jobs).map((j) => j.id), [6, 5, 7]);
  assert.deepEqual(displayOrder(jobs).map((j) => j.id), [4, 6, 5, 7, 3]);
  assert.deepEqual([...queuePlaces(jobs)], [[5, 1], [7, 2]]);
});
