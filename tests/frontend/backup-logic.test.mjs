import test from 'node:test';
import assert from 'node:assert/strict';
import { planSummary, planChanges, NOTHING_DELETED, YM_AGAIN } from '../../web/static/js/backup-logic.js';

const empty = {
  tags_added: 0, tag_links_added: 0, targets_added: 0, targets_updated: 0, mirrors_added: 0,
  usdb_user_set: false, needs_password: [], needs_google: [], default_target: null,
  telegram_set: false, telegram_needs_token: false, usdb_needs_password: false, yandex_needs_token: false,
};

test('planSummary: как в макете — добавлено, связи, пароль, ничего не удаляется', () => {
  const plan = { ...empty, tags_added: 3, targets_added: 1, tag_links_added: 41, needs_password: ['Pi'] };
  assert.deepEqual(planSummary(plan), [
    'Будет добавлено: 3 тега, 1 хранилище',
    'Теги песен: 41 связь',
    'Нужен пароль: Pi',
    'Ничего не удаляется',
  ]);
  assert.equal(NOTHING_DELETED, 'Ничего не удаляется');
});

test('planSummary: все пункты и склонения', () => {
  const plan = {
    ...empty, tags_added: 5, targets_added: 2, mirrors_added: 1, targets_updated: 11, tag_links_added: 2,
    default_target: 'Pi', usdb_user_set: true, usdb_needs_password: true, telegram_set: true,
    telegram_needs_token: true, needs_password: ['Pi', 'Диск'], needs_google: ['Гугл'], yandex_needs_token: true,
  };
  assert.deepEqual(planSummary(plan), [
    'Будет добавлено: 5 тегов, 2 хранилища, 1 зеркало',
    'Будет обновлено: 11 хранилищ',
    'Теги песен: 2 связи',
    'Основная цель: Pi',
    'Логин usdb: будет задан',
    'Telegram: чат и события',
    'Нужен пароль: Pi, Диск',
    'Нужен вход в Google: Гугл',
    'usdb: введите пароль заново',
    'Telegram: введите токен бота заново',
    'Яндекс Музыка: введите токен заново',
    'Ничего не удаляется',
  ]);
  assert.equal(YM_AGAIN, 'Яндекс Музыка: введите токен заново');
});

test('planSummary: повторная загрузка — менять нечего', () => {
  assert.deepEqual(planSummary(empty), ['Изменений нет — всё уже есть', 'Ничего не удаляется']);
  assert.equal(planChanges(empty), 0);
  assert.equal(planChanges({ ...empty, tag_links_added: 4, telegram_set: true }), 5);
  // напоминания о паролях — не изменения
  assert.equal(planChanges({ ...empty, needs_password: ['Pi'], yandex_needs_token: true }), 0);
});

test('planSummary: пустой ответ не роняет', () => {
  assert.deepEqual(planSummary({}), ['Изменений нет — всё уже есть', 'Ничего не удаляется']);
  assert.deepEqual(planSummary(null), ['Изменений нет — всё уже есть', 'Ничего не удаляется']);
});
