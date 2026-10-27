import test from 'node:test';
import assert from 'node:assert/strict';
import {
  KIND_LABELS, groupFindings, countLabel, fixButtons, fixCall, skippedLines, progressLine, checkedLine,
  FIXED_JOB, FIXED_DONE,
} from '../../web/static/js/check-logic.js';

const targets = [{ id: 'local', name: 'ПК' }, { id: 't_pi', name: 'Pi' }];
const finding = (o = {}) => ({
  id: 'f1', kind: 'no_audio', target_id: 't_pi', song_id: 's_pi', artist: 'Кино', title: 'Группа крови',
  detail: 'Нет файла звука', fix: { action: 'trash' }, fixes: [{ action: 'trash' }], ...o,
});

test('groupFindings: группы в порядке макета, пустые не показываются', () => {
  const report = { findings: [
    finding({ id: 'a', kind: 'diverged' }), finding({ id: 'b', kind: 'no_cover' }),
    finding({ id: 'c', kind: 'no_audio' }), finding({ id: 'd', kind: 'no_cover' }),
  ] };
  const groups = groupFindings(report);
  assert.deepEqual(groups.map((g) => [g.kind, g.label, g.count]),
    [['no_audio', 'Без звука', 1], ['no_cover', 'Без обложки', 2], ['diverged', 'Разошлись копии', 1]]);
  assert.deepEqual(groups[1].findings.map((f) => f.id), ['b', 'd']);
});

test('groupFindings: нет отчёта или проверки не было — пусто', () => {
  assert.deepEqual(groupFindings(null), []);
  assert.deepEqual(groupFindings({ findings: null }), []);
  assert.deepEqual(groupFindings({ findings: [] }), []);
});

test('KIND_LABELS: все шесть видов находок', () => {
  assert.deepEqual(Object.keys(KIND_LABELS).sort(),
    ['diverged', 'duplicate', 'encoding', 'no_audio', 'no_cover', 'video_missing']);
});

test('countLabel: дубли считаются парами', () => {
  assert.equal(countLabel('duplicate', 1), '1 пара');
  assert.equal(countLabel('duplicate', 2), '2 пары');
  assert.equal(countLabel('duplicate', 5), '5 пар');
  assert.equal(countLabel('no_audio', 3), '3');
});

test('fixButtons: подписи по действиям', () => {
  const f = finding({ fixes: [
    { action: 'copy_from', from_target: 'local', from_song_id: 's_pc' },
    { action: 'audio_from_video' }, { action: 'trash' }] });
  assert.deepEqual(fixButtons(f, targets).map((b) => [b.label, b.action, !!b.danger]), [
    ['Взять из копии в «ПК»', 'copy_from', false],
    ['Скачать звук по ссылке #VIDEO', 'audio_from_video', false],
    ['В корзину', 'trash', true],
  ]);
});

test('fixButtons: остальные виды', () => {
  const one = (fix, extra) => fixButtons(finding({ fixes: [fix], ...extra }), targets)[0];
  assert.equal(one({ action: 'cover_search' }).label, 'Найти обложку…');
  assert.equal(one({ action: 'video_remove' }).label, 'Убрать ссылку');
  assert.equal(one({ action: 'encoding' }).label, 'Исправить кодировку');
  assert.equal(one({ action: 'make_like', song_id: 's_pi', from_target: 'local', from_song_id: 's_pc' }).label,
    'Сделать как в «ПК»');
});

test('fixButtons: кодировку не угадали — кнопка погашена с причиной', () => {
  const b = fixButtons(finding({ fixes: [{ action: 'encoding', disabled: 'Не удалось угадать кодировку' }] }), targets)[0];
  assert.equal(b.disabled, 'Не удалось угадать кодировку');
});

test('fixButtons: дубль - «эта» и «другая»; без fixes берётся fix', () => {
  const f = finding({ kind: 'duplicate', fixes: [
    { action: 'keep_this', song_id: 's_pi', trash_song_id: 's_b' },
    { action: 'keep_this', song_id: 's_b', trash_song_id: 's_pi' }] });
  assert.deepEqual(fixButtons(f, targets).map((b) => b.label), ['Оставить эту', 'Оставить другую']);
  const g = finding({ fixes: undefined, fix: { action: 'trash' } });
  assert.deepEqual(fixButtons(g, targets).map((b) => b.label), ['В корзину']);
});

test('fixButtons: неизвестное хранилище - берётся id', () => {
  const b = fixButtons(finding({ fixes: [{ action: 'copy_from', from_target: 'gone', from_song_id: 'x' }] }), targets)[0];
  assert.equal(b.label, 'Взять из копии в «gone»');
});

test('fixCall: копия звука - заменяющее копирование в хранилище находки', () => {
  const c = fixCall({ action: 'copy_from', from_target: 'local', from_song_id: 's_pc' }, finding());
  assert.equal(c.method, 'copySongs');
  assert.deepEqual(c.args, [{ song_ids: ['s_pc'], target_id: 't_pi', replace: true, only_missing: false }]);
  assert.equal(c.mark, FIXED_JOB);
});

test('fixCall: make_like копирует из эталона в хранилище находки', () => {
  const c = fixCall({ action: 'make_like', song_id: 's_pi', from_target: 'local', from_song_id: 's_pc' }, finding());
  assert.deepEqual(c.args, [{ song_ids: ['s_pc'], target_id: 't_pi', replace: true, only_missing: false }]);
});

test('fixCall: корзина и «оставить» спрашивают подтверждение и удаляют нужную песню', () => {
  const t = fixCall({ action: 'trash' }, finding());
  assert.equal(t.method, 'bulkDelete');
  assert.deepEqual(t.args, [['s_pi']]);
  assert.equal(t.mark, FIXED_DONE);
  assert.ok(t.confirm.text.includes('Кино'));
  const k = fixCall({ action: 'keep_this', song_id: 's_pi', trash_song_id: 's_b' }, finding());
  assert.deepEqual(k.args, [['s_b']]);
  assert.ok(k.confirm);
});

test('fixCall: звук, ссылка, кодировка, обложка', () => {
  const a = fixCall({ action: 'audio_from_video' }, finding());
  assert.deepEqual([a.method, a.args, a.mark], ['audioFromVideo', ['s_pi'], FIXED_JOB]);
  const v = fixCall({ action: 'video_remove' }, finding());
  assert.equal(v.method, 'video');
  assert.deepEqual(v.args, ['s_pi', { remove: true }]);
  assert.equal(v.mark, FIXED_JOB);
  const e = fixCall({ action: 'encoding' }, finding());
  assert.deepEqual([e.method, e.args, e.mark], ['fixEncoding', ['s_pi'], FIXED_DONE]);
  const c = fixCall({ action: 'cover_search' }, finding());
  assert.equal(c.method, 'cover');
  assert.equal(c.mark, null);
});

test('skippedLines: недоступные хранилища', () => {
  assert.deepEqual(skippedLines({ skipped: [{ target_id: 'y', name: 'Яндекс Диск', error: 'нет связи' }] }),
    ['Хранилище «Яндекс Диск» недоступно — пропущено: нет связи']);
  assert.deepEqual(skippedLines({ skipped: [{ name: 'Pi' }] }), ['Хранилище «Pi» недоступно — пропущено']);
  assert.deepEqual(skippedLines({}), []);
});

test('progressLine: этап и процент идущей проверки', () => {
  assert.equal(progressLine({ state: 'running', stage: 'Проверка «Pi»', percent: 62.4 }), 'Проверка «Pi» · 62%');
  assert.equal(progressLine({ state: 'queued', percent: 0 }), 'Ожидает запуска');
});

test('checkedLine: дата последней проверки', () => {
  assert.equal(checkedLine({ findings: null }, () => 'x'), '');
  assert.equal(checkedLine({ findings: [], finished_at: '2026-10-27T11:02:00Z' }, () => 'сегодня 14:02'),
    'Последняя проверка: сегодня 14:02');
});
