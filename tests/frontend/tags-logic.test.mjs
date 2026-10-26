// Свои теги (tags-logic.js): палитра, ключ названия, ошибки ввода, теги песни.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  TAG_COLORS, DEFAULT_TAG_COLOR, TAG_NAME_MAX, COLOR_LABELS, tagNameKey, tagNameError, tagsById, songTagList,
} from '../../web/static/js/tags-logic.js';

const TAGS = [
  { id: 't1', name: 'Для вечеринки', color: 'blue' },
  { id: 't2', name: 'Ёлочные', color: 'teal' },
  { id: 't3', name: 'Разучить', color: 'orange' },
];

test('палитра: 8 цветов как на сервере, синий по умолчанию, у каждого русское имя', () => {
  assert.deepEqual(TAG_COLORS, ['blue', 'violet', 'pink', 'orange', 'yellow', 'teal', 'gray', 'red']);
  assert.equal(DEFAULT_TAG_COLOR, 'blue');
  assert.equal(TAG_NAME_MAX, 40);
  assert.equal(COLOR_LABELS.blue, 'синий');
  assert.equal(COLOR_LABELS.teal, 'бирюзовый');
  for (const c of TAG_COLORS) assert.ok(COLOR_LABELS[c], c);
});

test('tagNameKey: пробелы схлопнуты, без регистра, ё = е', () => {
  assert.equal(tagNameKey('  Для   ВЕЧЕРИНКИ '), 'для вечеринки');
  assert.equal(tagNameKey('Ёлочные'), tagNameKey('елочные'));
  assert.equal(tagNameKey(null), '');
});

test('tagNameError: пусто, длиннее 40, дубль — тексты сервера', () => {
  assert.equal(tagNameError('   ', TAGS), 'Введите название тега');
  assert.equal(tagNameError('я'.repeat(41), TAGS), 'Не длиннее 40 символов');
  assert.equal(tagNameError(' ' + 'я'.repeat(40) + ' ', TAGS), null);
  assert.equal(tagNameError('для  вечеринки', TAGS), 'Такой тег уже есть');
  assert.equal(tagNameError('елочные', TAGS), 'Такой тег уже есть');
  assert.equal(tagNameError('Медляк', TAGS), null);
});

test('tagNameError: переименование тега в себя же — не дубль', () => {
  assert.equal(tagNameError('ДЛЯ вечеринки', TAGS, 't1'), null);
  assert.equal(tagNameError('Разучить', TAGS, 't1'), 'Такой тег уже есть');
});

test('songTagList: свои теги песни по имени, неизвестные id пропущены', () => {
  const byId = tagsById(TAGS);
  assert.equal(byId.get('t2').name, 'Ёлочные');
  const song = { tags: ['t3', 'gone', 't1', 't2'] };
  assert.deepEqual(songTagList(song, byId).map((t) => t.id), ['t1', 't2', 't3']);
  assert.deepEqual(songTagList({}, byId), []);
  assert.deepEqual(songTagList(song, tagsById([])), []);
});
