// Чистая логика своих тегов: палитра, ключ названия и ошибки ввода (те же правила и тексты,
// что у сервера, karaoke_core.db.Tags), теги песни по id.

/** Палитра — как karaoke_core.db.TAG_COLORS; цвета заданы CSS-переменными --tag-<color>-bg/-fg. */
export const TAG_COLORS = ['blue', 'violet', 'pink', 'orange', 'yellow', 'teal', 'gray', 'red'];
export const DEFAULT_TAG_COLOR = 'blue';
export const TAG_NAME_MAX = 40;

export const COLOR_LABELS = {
  blue: 'синий',
  violet: 'фиолетовый',
  pink: 'розовый',
  orange: 'оранжевый',
  yellow: 'жёлтый',
  teal: 'бирюзовый',
  gray: 'серый',
  red: 'красный',
};

const clean = (name) => String(name ?? '').split(/\s+/).filter(Boolean).join(' ');

/** Ключ дубля названия (как db.tag_name_key): пробелы схлопнуты, без регистра, ё → е. */
export function tagNameKey(name) {
  return clean(name).toLowerCase().replaceAll('ё', 'е');
}

/** Ошибка названия тега или null; exceptId — тег, который переименовывают (с собой не дубль). */
export function tagNameError(name, tags = [], exceptId = null) {
  const value = clean(name);
  if (!value) return 'Введите название тега';
  if ([...value].length > TAG_NAME_MAX) return `Не длиннее ${TAG_NAME_MAX} символов`;
  const key = tagNameKey(value);
  if (tags.some((t) => t.id !== exceptId && tagNameKey(t.name) === key)) return 'Такой тег уже есть';
  return null;
}

/** Теги по id: Map id → {id, name, color}. */
export function tagsById(tags = []) {
  return new Map(tags.map((t) => [t.id, t]));
}

const coll = new Intl.Collator('ru', { sensitivity: 'base', numeric: true });

/** Свои теги песни (`song.tags` — id) по имени; неизвестные id (тег удалён) пропускаются. */
export function songTagList(song, byId) {
  return (song?.tags || []).map((id) => byId.get(id)).filter(Boolean)
    .map(({ id, name, color }) => ({ id, name, color }))
    .sort((a, b) => coll.compare(a.name, b.name));
}
