// Чистая логика страницы песни (#song?id=): плееры, сведения, размеры файлов, превью текста.
// details — ответ GET /api/songs/{id}/details.

const MEDIA = [
  ['audio', 'Песня'],
  ['instrumental', 'Минусовка'],
  ['vocals', 'Вокал'],
  ['video', 'Видео'],
];

/** Строки блока «Слушать и смотреть»: [{kind, label, name|null}] в постоянном порядке. */
export function mediaRows(details) {
  const media = details?.media || {};
  return MEDIA.map(([kind, label]) => ({ kind, label, name: media[kind] || null }));
}

const ORIGIN = { usdb: 'из usdb', files: 'импорт из файлов', url: 'импорт по ссылке' };

/** Происхождение песни словами. */
export function originLabel(song) {
  if (ORIGIN[song?.source]) return ORIGIN[song.source];
  if (song?.source === 'generated' || song?.own) return 'создана сервисом';
  return 'чужая';
}

const NBSP = ' ';

/** Число из заголовка по-русски: «312.5» → «312,5», «14230» → «14 230»; не число — как есть. */
function num(value) {
  const s = String(value).trim().replace(',', '.');
  if (!/^-?\d+(\.\d+)?$/.test(s)) return String(value).trim();
  const [int, frac] = s.split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return frac ? `${grouped},${frac}` : grouped;
}

/**
 * Сведения: [[подпись, значение, ссылка?]]; пустые пропускаются.
 * date(iso) — формат даты «обновлена» (на экране — ui.fmtDate).
 */
export function infoRows(details, { date = (iso) => iso } = {}) {
  const hd = details?.headers || {};
  const song = details?.song || {};
  const rows = [];
  const add = (label, value, href) => {
    const v = value == null ? '' : String(value).trim();
    if (v) rows.push(href ? [label, v, href] : [label, v]);
  };
  add('Автор', hd.author);
  add('Темп (BPM)', hd.bpm && num(hd.bpm));
  add('GAP', hd.gap && `${num(hd.gap)} мс`);
  add('Язык', hd.language);
  add('Год', hd.year);
  add('Жанр', hd.genre);
  add('Издание', hd.edition);
  add('Автор разметки', hd.creator);
  if (song.is_duet || details?.singers) {
    const s = details?.singers || {};
    const name = (v) => (v && String(v).trim()) || 'без имени';
    add('Дуэт', s.p1 || s.p2 ? `Певец 1: ${name(s.p1)} · Певец 2: ${name(s.p2)}` : 'да');
  }
  add('Происхождение', originLabel(song), song.source === 'usdb' ? details?.usdb_url || null : null);
  add('Обновлена', song.updated_at && date(song.updated_at));
  add('Папка', song.rel_dir);
  return rows;
}

const UNITS = ['КБ', 'МБ', 'ГБ'];

/** Размер файла: «512 Б», «6 КБ», «8,4 МБ», «48 МБ», «1,5 ГБ». */
export function fmtSize(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) return '';
  let n = Number(bytes);
  if (n < 1024) return `${Math.round(n)} Б`;
  let unit = -1;
  do { n /= 1024; unit += 1; } while (n >= 1024 && unit < UNITS.length - 1);
  if (unit === 0) return `${Math.max(1, Math.round(n))} КБ`;
  const v = n < 10 ? Math.round(n * 10) / 10 : Math.round(n);
  return `${String(v).replace('.', ',')} ${UNITS[unit]}`;
}

/** Первые n строк текста (`head`) и есть ли ещё (`more`); хвостовые пустые строки не в счёт. */
export function lyricsPreview(text, n = 12) {
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').replace(/\s+$/, '').split('\n');
  if (lines.length === 1 && !lines[0]) return { head: '', more: false };
  return { head: lines.slice(0, n).join('\n'), more: lines.length > n };
}
