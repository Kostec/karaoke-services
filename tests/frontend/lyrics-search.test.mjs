// Поиск текста (R01): чистые функции web/static/js/lyrics-search.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  stripLrc, usableHits, previewLines, fmtSeconds, searchBlocker, needsReplaceConfirm,
  lrcPlainText, lrcTimingDefault, lrcAfterEdit, DURATION_MISMATCH,
  lrcFormPart, lrcForNewText, LRC_SAVED,
  SOURCE_LABELS, sortHits, isLinkHit, hitLines, mergeHits,
} from '../../web/static/js/lyrics-search.js';

test('lrcPlainText: строка с N метками — N раз, по порядку времени (как --lyrics_timing форка)', () => {
  const lrc = '[ar:Кино]\n[offset:+200]\n[00:01.00]Раз\n[00:05.00][00:02.50]Припев  дважды\n[00:03.00]\n[00:04.00]Два\n';
  assert.equal(lrcPlainText(lrc), 'Раз\nПрипев дважды\n\nДва\nПрипев дважды');
  assert.equal(lrcPlainText('просто текст'), '');
});

test('lrcTimingDefault: правило 3 с между длительностью LRCLIB и mp3', () => {
  assert.deepEqual(lrcTimingDefault(200, 203), { checked: true, hint: '' });
  assert.deepEqual(lrcTimingDefault(200, 196.9), { checked: false, hint: DURATION_MISMATCH });
  assert.equal(DURATION_MISMATCH, 'Длительность не совпадает с mp3 — тайминги, скорее всего, от другой версии');
  assert.equal(lrcTimingDefault(null, 200).checked, false);
  assert.equal(lrcTimingDefault(200, null).checked, false);
});

test('lrcAfterEdit: правка текста LRC держит, очистка поля — сбрасывает', () => {
  const held = { lrc: '[00:01.00]Раз', duration: 200 };
  assert.equal(lrcAfterEdit(held, 'Раз, исправлено'), held);
  assert.equal(lrcAfterEdit(held, '  \n '), null);
  assert.equal(lrcAfterEdit(null, 'текст'), null);
});

test('lrcFormPart: LRC из поиска — передать, сохранённый или нетронутый — не слать, явный сброс — пустая часть', async () => {
  const { generateForm } = await import('../../web/static/js/api.js');
  const part = (held) => generateForm({ artist: 'A', title: 'T', lyrics: 'Раз', lyrics_lrc: lrcFormPart(held) });
  // перегенерация, текст не трогали: сервер возьмёт source/lyrics.lrc сам — поля нет
  assert.equal(part(null).has('lyrics_lrc'), false);
  assert.equal(part(LRC_SAVED).has('lyrics_lrc'), false);
  // правка без очистки не сбрасывает сохранённый
  assert.equal(lrcFormPart(lrcAfterEdit(LRC_SAVED, 'Раз, исправлено', true)), undefined);
  assert.equal(lrcFormPart(lrcAfterEdit(null, 'Раз, исправлено', true)), undefined);
  // явная очистка на перегенерации — пустая часть, даже если потом вписали новый текст
  const cleared = lrcAfterEdit(LRC_SAVED, ' ', true);
  assert.equal(lrcFormPart(cleared), '');
  assert.equal(lrcFormPart(lrcAfterEdit(cleared, 'Новый текст', true)), '');
  assert.equal(lrcFormPart(lrcAfterEdit(null, '', true)), '');
  // новая песня: сохранённого нет — очистка просто ничего не шлёт
  assert.equal(lrcFormPart(lrcAfterEdit(null, '', false)), undefined);
  // LRC из поиска — передаётся как есть
  assert.equal(lrcFormPart({ lrc: '[00:01.00]Раз', duration: 200 }), '[00:01.00]Раз');
  const sent = part({ lrc: '[00:01.00]Раз', duration: 200 }).get('lyrics_lrc');
  assert.equal(await sent.text(), '[00:01.00]Раз');
});

test('lrcForNewText: вставка или файл заменяют текст — LRC новый, иначе на перегенерации сохранённый сбросить', () => {
  assert.deepEqual(lrcForNewText({ synced: '[00:01.00]Раз', duration: 200 }, false), { lrc: '[00:01.00]Раз', duration: 200 });
  assert.deepEqual(lrcForNewText({ synced: '[00:01.00]Раз', duration: 200 }, true), { lrc: '[00:01.00]Раз', duration: 200 });
  assert.equal(lrcForNewText({ synced: null }, false), null);
  assert.equal(lrcForNewText(null, false), null); // файл текста на новой песне
  assert.equal(lrcFormPart(lrcForNewText({ synced: '  ' }, true)), '');
  assert.equal(lrcFormPart(lrcForNewText(null, true)), ''); // файл текста на перегенерации
});

test('usableHits: synced передаётся дальше', () => {
  const [hit] = usableHits([{ id: 1, text: 'Раз', synced: '[00:01.00]Раз' }]);
  assert.equal(hit.synced, '[00:01.00]Раз');
});

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

test('usableHits: вариант Genius (url без текста) остаётся, пустой без url — нет', () => {
  const link = { id: 'genius:1', source: 'genius', text: '', url: 'https://genius.com/x' };
  const hits = usableHits([link, { id: 'x', text: '', url: null }]);
  assert.deepEqual(hits.map((h) => h.id), ['genius:1']);
  assert.equal(hits[0].url, 'https://genius.com/x');
});

test('isLinkHit: только url и пустой текст', () => {
  assert.equal(isLinkHit({ text: '', url: 'https://g/x' }), true);
  assert.equal(isLinkHit({ text: 'Строка', url: 'https://g/x' }), false);
  assert.equal(isLinkHit({ text: 'Строка' }), false);
});

test('SOURCE_LABELS: подписи источников', () => {
  assert.deepEqual(SOURCE_LABELS, { lrclib: 'LRCLIB', netease: 'NetEase', genius: 'Genius' });
});

test('sortHits: синхронные первыми, внутри — порядок источников lrclib, netease, genius', () => {
  const list = [
    { id: 'genius:1', source: 'genius', text: '', url: 'u' },
    { id: 'netease:1', source: 'netease', text: 'a' },
    { id: 'lrclib:1', source: 'lrclib', text: 'a' },
    { id: 'netease:2', source: 'netease', text: 'a', synced: '[00:01.00]a' },
    { id: 'lrclib:2', source: 'lrclib', text: 'a', synced: '[00:01.00]a' },
  ];
  assert.deepEqual(sortHits(list).map((h) => h.id), ['lrclib:2', 'netease:2', 'lrclib:1', 'netease:1', 'genius:1']);
});

test('mergeHits: новые добавляются, повтор по id не дублируется, порядок как у sortHits', () => {
  const a = [{ id: 'lrclib:1', source: 'lrclib', text: 'a' }];
  const b = [{ id: 'netease:1', source: 'netease', text: 'a', synced: '[00:01.00]a' }, { id: 'lrclib:1', source: 'lrclib', text: 'a' }];
  assert.deepEqual(mergeHits(a, b).map((h) => h.id), ['netease:1', 'lrclib:1']);
  assert.deepEqual(mergeHits(null, a).map((h) => h.id), ['lrclib:1']);
});

test('hitLines: число непустых строк', () => {
  assert.equal(hitLines(['Раз', '', 'Два', '  ', 'Три'].join('\n')), 3);
  assert.equal(hitLines(''), 0);
});
