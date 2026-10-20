// Деление строки на слоги (спека §6): чистая функция web/static/js/editors/syllables.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import { toSyllables } from '../../web/static/js/editors/syllables.js';

test('слог на каждую гласную, одна согласная между гласными — в следующий слог', () => {
  assert.deepEqual(toSyllables('молоко'), ['мо', 'ло', 'ко']);
  assert.deepEqual(toSyllables('поэт'), ['по', 'эт']);
  // из пары согласных в следующий слог уходит одна
  assert.deepEqual(toSyllables('сказка'), ['сказ', 'ка']);
  assert.deepEqual(toSyllables('hello'), ['hel', 'lo']);
});

test('й ь ъ остаются с предыдущим слогом', () => {
  assert.deepEqual(toSyllables('мойка'), ['мой', 'ка']);
  assert.deepEqual(toSyllables('больше'), ['боль', 'ше']);
  assert.deepEqual(toSyllables('подъезд'), ['подъ', 'езд']);
  assert.deepEqual(toSyllables('семья'), ['семь', 'я']);
});

test('пробел перед словом — в начале его первого слога, «|» — принудительная граница', () => {
  assert.deepEqual(toSyllables('  мама мыла раму '), ['ма', 'ма', ' мы', 'ла', ' ра', 'му']);
  assert.deepEqual(toSyllables('сказ|ка про|стая'), ['сказ', 'ка', ' про', 'ста', 'я']);
  assert.deepEqual(toSyllables('при|вет'), ['при', 'вет']);
});

test('слово без гласных («в», «с») поётся вместе со следующим словом', () => {
  assert.deepEqual(toSyllables('шёл в дом'), ['шёл', ' в дом']);
  assert.deepEqual(toSyllables('с тобой'), ['с то', 'бой']);
  // в конце строки — к предыдущему слогу
  assert.deepEqual(toSyllables('вот и всё ж'), ['вот', ' и', ' всё ж']);
});

test('латинские гласные подряд — один слог (дифтонги), пустая строка — без слогов', () => {
  assert.deepEqual(toSyllables('you rain'), ['you', ' rain']);
  assert.deepEqual(toSyllables('beautiful'), ['beau', 'ti', 'ful']);
  assert.deepEqual(toSyllables('   '), []);
  assert.deepEqual(toSyllables('по|эт'), ['по', 'эт']);
});
