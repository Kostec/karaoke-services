// Выбор песен в «Песнях» (select-logic.js): набор id, скрытые фильтром, итог массовой операции, кнопки панели.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createSelection, bulkSummary, bulkButtons, selectionLabel, MAX_ZIP_SONGS,
} from '../../web/static/js/select-logic.js';

test('createSelection: toggle, has, size, ids в порядке отметки, clear', () => {
  const s = createSelection();
  assert.equal(s.size, 0);
  assert.equal(s.toggle('a'), true);
  assert.equal(s.toggle('b'), true);
  assert.equal(s.has('a'), true);
  assert.equal(s.size, 2);
  assert.deepEqual(s.ids(), ['a', 'b']);
  assert.equal(s.toggle('a'), false);
  assert.deepEqual(s.ids(), ['b']);
  s.clear();
  assert.equal(s.size, 0);
  assert.deepEqual(s.ids(), []);
});

test('setAll: «Все показанные» добавляет к выбору, не снимая прежних; on=false снимает только их', () => {
  const s = createSelection();
  s.toggle('hidden');
  s.setAll(['a', 'b', 'a']);
  assert.deepEqual(s.ids(), ['hidden', 'a', 'b']);
  assert.equal(s.allIn(['a', 'b']), true);
  assert.equal(s.allIn([]), false);
  s.setAll(['a', 'b'], false);
  assert.deepEqual(s.ids(), ['hidden']);
  assert.equal(s.allIn(['a', 'b']), false);
});

test('hiddenCount: отмеченные, которых нет среди показанных (выбор переживает смену фильтра)', () => {
  const s = createSelection();
  s.setAll(['a', 'b', 'c', 'd']);
  assert.equal(s.hiddenCount(['a', 'b', 'c', 'd', 'e']), 0);
  assert.equal(s.hiddenCount(['a', 'e']), 3); // фильтр сменился — выбор тот же
  assert.equal(s.size, 4);
  assert.equal(s.hiddenCount(new Set(['b'])), 3);
});

test('selectionLabel: «Выбрано N» и «ещё M скрыты фильтром»', () => {
  assert.deepEqual(selectionLabel(5, 2), { main: 'Выбрано 5', sub: 'ещё 2 скрыты фильтром' });
  assert.deepEqual(selectionLabel(1, 1), { main: 'Выбрано 1', sub: 'ещё 1 скрыта фильтром' });
  assert.deepEqual(selectionLabel(3, 0), { main: 'Выбрано 3', sub: '' });
  assert.deepEqual(selectionLabel(0, 0), { main: 'Ничего не выбрано', sub: '' });
});

test('bulkSummary минусовки: «Готово: 12. Пропущено: 3» с причинами по песням', () => {
  const names = { s2: 'Кино — Группа крови', s3: 'Queen — Bohemian Rhapsody', s4: 'Градусы — Режиссёр' };
  const res = {
    queued: Array.from({ length: 12 }, (_, i) => i + 1),
    skipped: [{ song_id: 's2', reason: 'уже есть минусовка' }, { song_id: 's3', reason: 'уже в очереди' }],
    errors: [{ song_id: 's4', detail: 'Песня не найдена' }],
  };
  const sum = bulkSummary(res, (id) => names[id]);
  assert.equal(sum.text, 'Готово: 12. Пропущено: 3');
  assert.deepEqual(sum.lines, [
    { song_id: 's2', name: 'Кино — Группа крови', reason: 'уже есть минусовка' },
    { song_id: 's3', name: 'Queen — Bohemian Rhapsody', reason: 'уже в очереди' },
    { song_id: 's4', name: 'Градусы — Режиссёр', reason: 'Песня не найдена' },
  ]);
});

test('bulkSummary: теги (updated), удаление (removed), без пропусков — только «Готово: N»', () => {
  assert.deepEqual(bulkSummary({ updated: 4, errors: [] }), { text: 'Готово: 4', lines: [] });
  const del = bulkSummary({ removed: ['a', 'b'], errors: [{ song_id: 'x', detail: 'Папка результата недоступна' }] });
  assert.equal(del.text, 'Готово: 2. Пропущено: 1');
  assert.deepEqual(del.lines, [{ song_id: 'x', name: 'x', reason: 'Папка результата недоступна' }]);
});

test('bulkSummary копирования: skipped числом — одна строка «уже есть в хранилище»', () => {
  const sum = bulkSummary({ queued: [1], skipped: 2, errors: [] });
  assert.equal(sum.text, 'Готово: 1. Пропущено: 2');
  assert.deepEqual(sum.lines, [{ song_id: null, name: '', reason: 'уже есть в хранилище: 2' }]);
});

test('bulkButtons: хранилище недоступно — погашено всё, кроме «Теги…», с причиной', () => {
  const off = bulkButtons({ count: 3, outputOk: false, others: 1 });
  assert.equal(off.tags, false);
  for (const k of ['copy', 'zip', 'instrumental', 'delete']) {
    assert.equal(off[k], 'Хранилище недоступно — действия с файлами отключены', k);
  }
  const on = bulkButtons({ count: 3, outputOk: true, others: 1 });
  assert.deepEqual(on, { tags: false, copy: false, zip: false, instrumental: false, delete: false });
});

test('bulkButtons: ничего не выбрано, нет других хранилищ, zip больше 500', () => {
  const none = bulkButtons({ count: 0, outputOk: true, others: 1 });
  for (const k of ['tags', 'copy', 'zip', 'instrumental', 'delete']) assert.equal(none[k], 'Ничего не выбрано', k);
  assert.match(bulkButtons({ count: 2, outputOk: true, others: 0 }).copy, /Других хранилищ нет/);
  assert.equal(MAX_ZIP_SONGS, 500);
  assert.equal(bulkButtons({ count: 501, outputOk: true, others: 1 }).zip, 'В один архив — не больше 500 песен');
  assert.equal(bulkButtons({ count: 500, outputOk: true, others: 1 }).zip, false);
  assert.match(bulkButtons({ count: 1001, outputOk: true, others: 1 }).delete, /не больше 1000/);
});
