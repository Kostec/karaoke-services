// Поиск текста (R01): чистые функции web/static/js/lyrics-search.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  stripLrc, usableHits, previewLines, fmtSeconds, searchBlocker, needsReplaceConfirm,
} from '../../web/static/js/lyrics-search.js';

test('stripLrc: метки времени срезаются, метаданные убираются', () => {
  const lrc = '[ar:Кино]\r\n[ti:Звезда]\r\n[00:12.34] Песен ещё не написанных\n[00:15.00]\n\n\n[00:17.5]Сколько?\n[01:02.003][01:05.00]Скажи  \n';
  assert.equal(stripLrc(lrc), 'Песен ещё не написанных\n\nСколько?\nСкажи');
});

test('stripLrc: обычный текст не меняется, кроме переводов строк и краёв', () => {
  assert.equal(stripLrc('\nКуплет [не метка]\r\nвторая\n'), 'Куплет [не метка]\nвторая');
  assert.equal(stripLrc(''), '');
  assert.equal(stripLrc(null), '');
});

test('usableHits: без текста и инструменталы отброшены, LRC очищен, не больше 10', () => {
  const list = [
    { id: 1, artist: 'A', title: 'T', text: '' },
    { id: 2, artist: 'A', title: 'T', text: '  \n ' },
    { id: 3, artist: 'A', title: 'T', text: 'x', instrumental: true },
    { id: 4, artist: 'A', title: 'T', text: '[00:01.00]Раз\n[00:02.00]Два' },
    ...Array.from({ length: 12 }, (_, i) => ({ id: 10 + i, artist: 'A', title: 'T', text: 'Строка' })),
  ];
  const hits = usableHits(list);
  assert.equal(hits.length, 10);
  assert.equal(hits[0].id, 4);
  assert.equal(hits[0].text, 'Раз\nДва');
  assert.deepEqual(usableHits(null), []);
});

test('previewLines: первые непустые строки', () => {
  assert.deepEqual(previewLines('\nРаз\n\nДва\nТри\nЧетыре'), ['Раз', 'Два', 'Три']);
  assert.deepEqual(previewLines('Одна', 2), ['Одна']);
});

test('fmtSeconds: м:сс', () => {
  assert.equal(fmtSeconds(285), '4:45');
  assert.equal(fmtSeconds(61.6), '1:02');
  assert.equal(fmtSeconds(null), '');
  assert.equal(fmtSeconds(0), '');
});

test('searchBlocker: без исполнителя или названия — подсказка', () => {
  assert.equal(searchBlocker('', 'T'), 'Укажите исполнителя и название');
  assert.equal(searchBlocker('A', '  '), 'Укажите исполнителя и название');
  assert.equal(searchBlocker(' A ', 'T'), '');
});

test('needsReplaceConfirm: только если в поле уже есть текст', () => {
  assert.equal(needsReplaceConfirm(''), false);
  assert.equal(needsReplaceConfirm(' \n '), false);
  assert.equal(needsReplaceConfirm('мой текст'), true);
});
