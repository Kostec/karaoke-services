// Резервная копия настроек (истории 66–68): чистая логика карточки «Резервная копия» в settings.js.
// План загрузки — ответ POST /api/settings/backup?apply=0 (karaoke_core.backup.ImportPlan.to_dict).

export const NOTHING_DELETED = 'Ничего не удаляется';
export const NO_CHANGES = 'Изменений нет — всё уже есть';
export const YM_AGAIN = 'Яндекс Музыка: введите токен заново';

function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

const count = (n, one, few, many) => `${n} ${plural(n, one, few, many)}`;
const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
const names = (v) => (Array.isArray(v) ? v.filter(Boolean) : []);

/** Сколько изменений сделает «Применить» (напоминания о паролях и токенах — не изменения). */
export function planChanges(plan) {
  const p = plan || {};
  return num(p.tags_added) + num(p.tag_links_added) + num(p.targets_added) + num(p.targets_updated)
    + num(p.mirrors_added) + (p.default_target ? 1 : 0) + (p.usdb_user_set ? 1 : 0) + (p.telegram_set ? 1 : 0);
}

/** Строки предпросмотра «что изменится»; последняя — всегда «Ничего не удаляется». */
export function planSummary(plan) {
  const p = plan || {};
  const out = [];
  const added = [];
  if (num(p.tags_added)) added.push(count(num(p.tags_added), 'тег', 'тега', 'тегов'));
  if (num(p.targets_added)) added.push(count(num(p.targets_added), 'хранилище', 'хранилища', 'хранилищ'));
  if (num(p.mirrors_added)) added.push(count(num(p.mirrors_added), 'зеркало', 'зеркала', 'зеркал'));
  if (added.length) out.push(`Будет добавлено: ${added.join(', ')}`);
  if (num(p.targets_updated)) {
    out.push(`Будет обновлено: ${count(num(p.targets_updated), 'хранилище', 'хранилища', 'хранилищ')}`);
  }
  if (num(p.tag_links_added)) out.push(`Теги песен: ${count(num(p.tag_links_added), 'связь', 'связи', 'связей')}`);
  if (p.default_target) out.push(`Основная цель: ${p.default_target}`);
  if (p.usdb_user_set) out.push('Логин usdb: будет задан');
  if (p.telegram_set) out.push('Telegram: чат и события');
  if (!out.length) out.push(NO_CHANGES);
  if (names(p.needs_password).length) out.push(`Нужен пароль: ${names(p.needs_password).join(', ')}`);
  if (names(p.needs_google).length) out.push(`Нужен вход в Google: ${names(p.needs_google).join(', ')}`);
  if (p.usdb_needs_password) out.push('usdb: введите пароль заново');
  if (p.telegram_needs_token) out.push('Telegram: введите токен бота заново');
  if (p.yandex_needs_token) out.push(YM_AGAIN);
  out.push(NOTHING_DELETED);
  return out;
}
