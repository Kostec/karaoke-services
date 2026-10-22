// «Настройки → Куда выкладывать» (targets-logic.js): тело запроса по типу формы, поле ошибки
// сервера → поле формы, подсказка «подключите Google Диск с компьютера», «тот же адрес и логин».
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  targetBody, savedBody, formKind, fieldTarget, needsLocalHint, sameAccount, KIND_FIELDS,
} from '../../web/static/js/targets-logic.js';

const all = { name: ' Имя ', host: ' 10.0.0.9 ', share: 'karaoke', path: ' songs ', user: ' pi ',
  url: 'https://x', client_id: 'cid', password: ' p w ' };

test('targetBody: только поля своего типа, обрезка пробелов, пароль как есть', () => {
  const smb = targetBody('smb', all);
  assert.deepEqual(smb, { kind: 'smb', name: 'Имя', host: '10.0.0.9', share: 'karaoke', path: 'songs',
    user: 'pi', password: ' p w ' });
  assert.deepEqual(targetBody('local', { ...all, password: '' }), { kind: 'local', name: 'Имя', path: 'songs' });
  assert.deepEqual(targetBody('gdrive', { ...all, password: '' }, { id: 't_1' }),
    { id: 't_1', kind: 'gdrive', name: 'Имя', client_id: 'cid', path: 'songs' });
  assert.equal('password' in targetBody('webdav', { ...all, password: '' }), false); // пусто — «не менять»
});

test('targetBody: Яндекс Диск уходит как webdav с preset=yandex, без адреса', () => {
  assert.deepEqual(targetBody('yandex', all), { kind: 'webdav', preset: 'yandex', name: 'Имя', user: 'pi',
    path: 'songs', password: ' p w ' });
});

test('formKind и savedBody: сохранённый Яндекс Диск открывается формой yandex', () => {
  const ya = { id: 't_2', kind: 'webdav', preset: 'yandex', url: 'https://webdav.yandex.ru', name: 'Я',
    user: 'me', path: 'K', has_password: true };
  assert.equal(formKind(ya), 'yandex');
  assert.equal(formKind({ kind: 'webdav', preset: '' }), 'webdav');
  assert.deepEqual(savedBody(ya), { id: 't_2', kind: 'webdav', preset: 'yandex', name: 'Я', user: 'me', path: 'K' });
});

test('fieldTarget: поле ответа → поле формы этого типа', () => {
  assert.equal(fieldTarget('password', 'smb'), 'password');
  assert.equal(fieldTarget('host', 'smb'), 'host');
  assert.equal(fieldTarget('host', 'webdav'), null);
  assert.equal(fieldTarget('url', 'yandex'), null);
  assert.equal(fieldTarget('path', 'local'), 'folder');
  assert.equal(fieldTarget('path', 'gdrive'), 'path');
  assert.equal(fieldTarget('password', 'local'), null);
  assert.equal(fieldTarget('name', 'local'), 'name');
  assert.equal(fieldTarget('kind', 'smb'), null);
  assert.equal(fieldTarget(undefined, 'smb'), null);
  assert.deepEqual(Object.keys(KIND_FIELDS).sort(), ['gdrive', 'local', 'smb', 'webdav', 'yandex']);
});

test('needsLocalHint: подсказка, если открыто не с localhost/127.0.0.1', () => {
  for (const h of ['localhost', '127.0.0.1', '[::1]']) assert.equal(needsLocalHint(h), false, h);
  for (const h of ['192.168.0.10', 'pc.local', '']) assert.equal(needsLocalHint(h), true, h);
});

test('sameAccount: пустой пароль = «не менять» только при том же адресе и логине', () => {
  const smb = { kind: 'smb', host: '10.0.0.9', share: 'karaoke', user: 'pi', has_password: true };
  assert.equal(sameAccount('smb', { host: ' 10.0.0.9', share: '/karaoke/', user: 'pi' }, smb), true);
  assert.equal(sameAccount('smb', { host: '10.6.6.6', share: 'karaoke', user: 'pi' }, smb), false);
  assert.equal(sameAccount('smb', { host: '10.0.0.9', share: 'karaoke', user: 'pi' }, { ...smb, has_password: false }), false);
  assert.equal(sameAccount('smb', { host: '10.0.0.9' }, null), false);
  const dav = { kind: 'webdav', url: 'https://d.example', user: 'me', has_password: true };
  assert.equal(sameAccount('webdav', { url: 'https://d.example/', user: 'me' }, dav), true);
  assert.equal(sameAccount('yandex', { user: 'me' }, { ...dav, preset: 'yandex' }), true);
  assert.equal(sameAccount('gdrive', { client_id: 'c2' }, { kind: 'gdrive', client_id: 'c1', has_password: true }), false);
});
