// «Переименовать…» (rename-logic.js): проверка полей, тело запроса, своя копия в ответе.
import test from 'node:test';
import assert from 'node:assert/strict';
import { renameErrors, renameBody, ownRename } from '../../web/static/js/rename-logic.js';

const SONG = { song_id: 's1', target_id: 'local', artist: 'Кино', title: 'Группа крови' };

test('пустые поля — ошибка у своего поля', () => {
  assert.deepEqual(renameErrors({ artist: '  ', title: '' }, SONG),
    { artist: 'Введите исполнителя', title: 'Введите название' });
  assert.deepEqual(renameErrors({ artist: 'Кино', title: ' ' }, SONG), { title: 'Введите название' });
});

test('то же имя (с пробелами по краям) — «Имя не изменилось»; смена регистра — можно', () => {
  assert.deepEqual(renameErrors({ artist: ' Кино ', title: 'Группа крови ' }, SONG), { title: 'Имя не изменилось' });
  assert.deepEqual(renameErrors({ artist: 'КИНО', title: 'Группа крови' }, SONG), {});
  assert.deepEqual(renameErrors({ artist: 'Кино', title: 'Звезда по имени Солнце' }, SONG), {});
});

test('тело запроса — id песни и имя без пробелов по краям', () => {
  assert.deepEqual(renameBody(SONG, { artist: ' Кино ', title: ' Пачка сигарет ' }),
    { song_id: 's1', artist: 'Кино', title: 'Пачка сигарет' });
});

test('своя копия — по хранилищу, иначе первая; пустой ответ — null', () => {
  const res = { jobs: [{ job_id: 1, target_id: 't_1', song_id: 'n1' }, { job_id: 2, target_id: 'local', song_id: 'n2' }] };
  assert.equal(ownRename(res, 'local').song_id, 'n2');
  assert.equal(ownRename(res, 't_x').song_id, 'n1');
  assert.equal(ownRename({ jobs: [] }, 'local'), null);
  assert.equal(ownRename(null, 'local'), null);
});
