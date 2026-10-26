// Вкладка «Песни» (songs-filter.js): фильтры, сортировки, счётчики исполнителей, адрес #songs?…
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterSongs, artistCounts, parseFilter, filterParams, isDefaultFilter, SORTS, DEFAULT_FILTER, publishLine,
  activeFilterCount,
} from '../../web/static/js/songs-filter.js';

const S = (id, o = {}) => ({ song_id: id, artist: 'A', title: id, instrumental: null, video: null,
  is_duet: false, cover: null, own: false, source: null, updated_at: null, tags: [], ...o });

const items = [
  S('Ёлка', { artist: 'Ёлка', instrumental: 'x [Instrumental].mp3', cover: 'c.jpg', own: true,
    source: 'generated', updated_at: '2024-03-01T10:00:00+00:00' }),
  S('Дуэт', { artist: 'Пара', is_duet: true, video: 'v.mp4', own: true, source: 'usdb',
    updated_at: '2024-01-01T10:00:00+00:00' }),
  S('Чужая', { artist: 'Пара', cover: 'c.jpg', updated_at: '2024-02-01T10:00:00+00:00' }),
  S('Архив', { artist: 'Би-2', own: true, source: 'files' }),
];
items[0].tags = ['t1'];
items[1].tags = ['t1', 't2'];
const ids = (f) => filterSongs(items, { ...DEFAULT_FILTER, ...f }).map((s) => s.song_id);

test('умолчание — все песни, по исполнителю, затем по названию', () => {
  assert.deepEqual(ids({}), ['Архив', 'Ёлка', 'Дуэт', 'Чужая']);
});

test('поиск по исполнителю и названию без регистра и ё', () => {
  assert.deepEqual(ids({ q: 'елк' }), ['Ёлка']);
  assert.deepEqual(ids({ q: 'ПАРА' }), ['Дуэт', 'Чужая']);
  assert.deepEqual(ids({ q: 'дуэт' }), ['Дуэт']);
  assert.deepEqual(ids({ q: '  ' }), ['Архив', 'Ёлка', 'Дуэт', 'Чужая']);
});

test('исполнитель — точное совпадение', () => {
  assert.deepEqual(ids({ artist: 'Пара' }), ['Дуэт', 'Чужая']);
  assert.deepEqual(ids({ artist: 'Пар' }), []);
});

test('минусовка, видео, дуэт, обложка: есть/нет', () => {
  assert.deepEqual(ids({ instrumental: 'yes' }), ['Ёлка']);
  assert.deepEqual(ids({ instrumental: 'no' }), ['Архив', 'Дуэт', 'Чужая']);
  assert.deepEqual(ids({ video: 'yes' }), ['Дуэт']);
  assert.deepEqual(ids({ video: 'no' }), ['Архив', 'Ёлка', 'Чужая']);
  assert.deepEqual(ids({ duet: 'duet' }), ['Дуэт']);
  assert.deepEqual(ids({ duet: 'solo' }), ['Архив', 'Ёлка', 'Чужая']);
  assert.deepEqual(ids({ cover: 'yes' }), ['Ёлка', 'Чужая']);
  assert.deepEqual(ids({ cover: 'no' }), ['Архив', 'Дуэт']);
});

test('происхождение: сгенерирована здесь / импорт / чужая', () => {
  assert.deepEqual(ids({ origin: 'generated' }), ['Ёлка']);
  assert.deepEqual(ids({ origin: 'import' }), ['Архив', 'Дуэт']);
  assert.deepEqual(ids({ origin: 'foreign' }), ['Чужая']);
});

test('фильтры складываются по И', () => {
  assert.deepEqual(ids({ artist: 'Пара', cover: 'yes' }), ['Чужая']);
  assert.deepEqual(ids({ artist: 'Пара', cover: 'yes', origin: 'import' }), []);
  assert.deepEqual(ids({ q: 'а', instrumental: 'no', duet: 'solo' }), ['Архив', 'Чужая']);
});

test('сортировки: название, дата ↓ и ↑ (без даты — в конце)', () => {
  assert.deepEqual(SORTS.map((s) => s.id), ['artist', 'title', 'date_desc', 'date_asc']);
  assert.deepEqual(ids({ sort: 'title' }), ['Архив', 'Дуэт', 'Ёлка', 'Чужая']);
  assert.deepEqual(ids({ sort: 'date_desc' }), ['Ёлка', 'Чужая', 'Дуэт', 'Архив']);
  assert.deepEqual(ids({ sort: 'date_asc' }), ['Дуэт', 'Чужая', 'Ёлка', 'Архив']);
});

test('filterSongs не меняет исходный массив', () => {
  const copy = items.map((s) => s.song_id);
  filterSongs(items, { ...DEFAULT_FILTER, sort: 'date_desc' });
  assert.deepEqual(items.map((s) => s.song_id), copy);
});

test('artistCounts: исполнители по алфавиту с числом песен', () => {
  assert.deepEqual(artistCounts(items), [
    { artist: 'Би-2', count: 1 }, { artist: 'Ёлка', count: 1 }, { artist: 'Пара', count: 2 }]);
  assert.deepEqual(artistCounts([S('x', { artist: '' })]), []);
});

test('parseFilter: умолчания и отброс неизвестных значений', () => {
  assert.deepEqual(parseFilter(new URLSearchParams('')), DEFAULT_FILTER);
  const f = parseFilter(new URLSearchParams('q=ёлка&video=yes&duet=maybe&sort=bogus&origin=import'));
  assert.deepEqual(f, { ...DEFAULT_FILTER, q: 'ёлка', video: 'yes', origin: 'import' });
});

test('filterParams: только отличное от умолчаний; круговой parseFilter(filterParams(f))', () => {
  assert.deepEqual(filterParams(DEFAULT_FILTER), {});
  const f = { q: 'а б', artist: 'Пара', instrumental: 'no', video: 'yes', duet: 'solo', cover: 'no',
    origin: 'foreign', tag: 't_1', sort: 'date_asc' };
  assert.deepEqual(parseFilter(new URLSearchParams(filterParams(f))), f);
  const one = { ...DEFAULT_FILTER, cover: 'yes' };
  assert.deepEqual(filterParams(one), { cover: 'yes' });
  assert.deepEqual(parseFilter(new URLSearchParams(filterParams(one))), one);
});

test('isDefaultFilter: сортировка фильтром не считается', () => {
  assert.equal(isDefaultFilter(DEFAULT_FILTER), true);
  assert.equal(isDefaultFilter({ ...DEFAULT_FILTER, sort: 'title' }), true);
  assert.equal(isDefaultFilter({ ...DEFAULT_FILTER, q: 'x' }), false);
});

test('publishLine: «Локальное хранилище + «X»», если основная — не локальная', () => {
  const targets = [{ id: 'local', name: 'Локальное хранилище' }, { id: 't_1', name: 'Pi' }, { id: 't_2', name: '', label: 'smb://1.2.3.4/k' }];
  assert.equal(publishLine({ targets, default_id: 't_1' }), 'Выкладка: Локальное хранилище + «Pi»');
  assert.equal(publishLine({ targets, default_id: 't_2' }), 'Выкладка: Локальное хранилище + «smb://1.2.3.4/k»');
  assert.equal(publishLine({ targets, default_id: 'local' }), 'Выкладка: Локальное хранилище');
  assert.equal(publishLine({ targets, default_id: 't_gone' }), 'Выкладка: Локальное хранилище');
});

test('свой тег: по id, «none» — без своих тегов, пусто — все', () => {
  assert.equal(DEFAULT_FILTER.tag, '');
  assert.deepEqual(ids({ tag: 't1' }), ['Ёлка', 'Дуэт']);
  assert.deepEqual(ids({ tag: 't2' }), ['Дуэт']);
  assert.deepEqual(ids({ tag: 'none' }), ['Архив', 'Чужая']);
  assert.deepEqual(ids({ tag: 'gone' }), []);
  assert.deepEqual(filterSongs([{ ...S('x'), tags: undefined }], { ...DEFAULT_FILTER, tag: 'none' }).length, 1);
});

test('parseFilter: tag — строкой; в адресе tag=<id> / tag=none', () => {
  assert.equal(parseFilter(new URLSearchParams('tag=none')).tag, 'none');
  assert.equal(parseFilter(new URLSearchParams('tag=t_ab')).tag, 't_ab');
  assert.deepEqual(filterParams({ ...DEFAULT_FILTER, tag: 'none' }), { tag: 'none' });
  assert.equal(isDefaultFilter({ ...DEFAULT_FILTER, tag: 't1' }), false);
});

test('activeFilterCount: включённые фильтры без поиска и сортировки', () => {
  assert.equal(activeFilterCount(DEFAULT_FILTER), 0);
  assert.equal(activeFilterCount({ ...DEFAULT_FILTER, q: 'x', sort: 'title' }), 0);
  assert.equal(activeFilterCount({ ...DEFAULT_FILTER, artist: 'Пара', video: 'yes', tag: 'none' }), 3);
  assert.equal(activeFilterCount({ ...DEFAULT_FILTER, instrumental: 'no', duet: 'solo', cover: 'yes', origin: 'import' }), 4);
});
