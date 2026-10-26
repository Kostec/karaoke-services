// Чистая логика вкладки «Песни»: фильтры, сортировка, исполнители, состояние в адресе (#songs?…).
// Индекс хранилища приходит целиком, поэтому всё считается на клиенте.

/** Сортировки списка: id — значение `sort` в адресе. */
export const SORTS = [
  { id: 'artist', label: 'По исполнителю' },
  { id: 'title', label: 'По названию' },
  { id: 'date_desc', label: 'Сначала новые' },
  { id: 'date_asc', label: 'Сначала старые' },
];

/** Допустимые значения фильтров-выборов (первое — умолчание «все»). */
export const CHOICES = {
  instrumental: ['all', 'yes', 'no'],
  video: ['all', 'yes', 'no'],
  duet: ['all', 'duet', 'solo'],
  cover: ['all', 'yes', 'no'],
  origin: ['all', 'generated', 'import', 'foreign'],
};

/** `tag`: '' — все, 'none' — без своих тегов, иначе id своего тега. */
export const DEFAULT_FILTER = Object.freeze({
  q: '', artist: '', instrumental: 'all', video: 'all', duet: 'all', cover: 'all', origin: 'all', tag: '',
  sort: 'artist',
});

export const NO_TAG = 'none';

function hasTag(tag, tags) {
  if (!tag) return true;
  const list = Array.isArray(tags) ? tags : [];
  return tag === NO_TAG ? !list.length : list.includes(tag);
}

const IMPORT_SOURCES = ['usdb', 'files', 'url'];
const coll = new Intl.Collator('ru', { sensitivity: 'base', numeric: true });

const fold = (s) => String(s || '').toLocaleLowerCase('ru').replaceAll('ё', 'е');

/** Происхождение песни: generated | import | foreign. */
export function originOf(song) {
  if (IMPORT_SOURCES.includes(song.source)) return 'import';
  if (song.source === 'generated' || song.own) return 'generated';
  return 'foreign';
}

function has(choice, value) {
  return choice === 'all' || (choice === 'yes') === !!value;
}

function byName(a, b, first, second) {
  return coll.compare(a[first] || '', b[first] || '') || coll.compare(a[second] || '', b[second] || '');
}

function byDate(a, b, dir) {
  const x = a.updated_at || '';
  const y = b.updated_at || '';
  if (!x || !y) return (x ? 0 : 1) - (y ? 0 : 1) || byName(a, b, 'artist', 'title');
  return (x < y ? -1 : x > y ? 1 : 0) * dir || byName(a, b, 'artist', 'title');
}

const COMPARE = {
  artist: (a, b) => byName(a, b, 'artist', 'title'),
  title: (a, b) => byName(a, b, 'title', 'artist'),
  date_desc: (a, b) => byDate(a, b, -1),
  date_asc: (a, b) => byDate(a, b, 1),
};

/** Песни под фильтр `f` (все условия по И), отсортированные; исходный массив не меняется. */
export function filterSongs(items, f) {
  const q = fold(f.q).trim();
  const artist = fold(f.artist);
  const out = items.filter((s) => (!q || fold(s.artist).includes(q) || fold(s.title).includes(q))
    && (!artist || fold(s.artist) === artist)
    && has(f.instrumental, s.instrumental)
    && has(f.video, s.video)
    && (f.duet === 'all' || (f.duet === 'duet') === !!s.is_duet)
    && has(f.cover, s.cover)
    && (f.origin === 'all' || originOf(s) === f.origin)
    && hasTag(f.tag, s.tags));
  return out.sort(COMPARE[f.sort] || COMPARE.artist);
}

/** Исполнители хранилища с числом песен, по алфавиту: `[{artist, count}]`. */
export function artistCounts(items) {
  const counts = new Map();
  for (const s of items) {
    const a = (s.artist || '').trim();
    if (a) counts.set(a, (counts.get(a) || 0) + 1);
  }
  return [...counts].map(([artist, count]) => ({ artist, count }))
    .sort((a, b) => coll.compare(a.artist, b.artist));
}

/** Фильтр из параметров адреса (URLSearchParams); неизвестные значения — умолчания. */
export function parseFilter(params) {
  const get = (k) => (params && typeof params.get === 'function' ? params.get(k) : params?.[k]) ?? '';
  const f = { ...DEFAULT_FILTER, q: String(get('q')), artist: String(get('artist')), tag: String(get('tag')) };
  for (const [k, values] of Object.entries(CHOICES)) {
    if (values.includes(get(k))) f[k] = get(k);
  }
  if (SORTS.some((s) => s.id === get('sort'))) f.sort = get('sort');
  return f;
}

/** Параметры адреса для фильтра: только отличное от умолчаний. */
export function filterParams(f) {
  const out = {};
  for (const k of Object.keys(DEFAULT_FILTER)) {
    if (f[k] !== undefined && f[k] !== DEFAULT_FILTER[k]) out[k] = String(f[k]);
  }
  return out;
}

/** Ничего не отфильтровано (сортировка не в счёт). */
export function isDefaultFilter(f) {
  return Object.keys(DEFAULT_FILTER).every((k) => k === 'sort' || (f[k] ?? DEFAULT_FILTER[k]) === DEFAULT_FILTER[k]);
}

/** Сколько фильтров включено — счётчик кнопки «Фильтры (N)»; поиск и сортировка не в счёт. */
export function activeFilterCount(f) {
  return Object.keys(DEFAULT_FILTER)
    .filter((k) => k !== 'q' && k !== 'sort' && (f[k] ?? DEFAULT_FILTER[k]) !== DEFAULT_FILTER[k]).length;
}

const LOCAL_ID = 'local';

/** Строка форм «Новая песня» и «Импорт» по ответу GET /api/targets: новая песня выкладывается
 *  в локальное хранилище и, если основная цель другая, ещё и в неё. */
export function publishLine({ targets = [], default_id: def } = {}) {
  const name = (t) => t?.name || t?.label || '';
  const local = name(targets.find((t) => t.id === LOCAL_ID)) || 'Локальное хранилище';
  const main = def && def !== LOCAL_ID ? targets.find((t) => t.id === def) : null;
  return main ? `Выкладка: ${local} + «${name(main)}»` : `Выкладка: ${local}`;
}
