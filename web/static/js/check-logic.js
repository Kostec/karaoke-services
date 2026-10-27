// Чистая логика раздела «Проверка библиотеки» (без DOM): группы находок, кнопки исправлений,
// вызовы API под них, строки статуса. Отчёт — формат libcheck.make_report.

export const KIND_LABELS = {
  no_audio: 'Без звука',
  no_cover: 'Без обложки',
  video_missing: 'Битая ссылка #VIDEO',
  encoding: 'Кодировка',
  duplicate: 'Дубли',
  diverged: 'Разошлись копии',
};
/** Порядок групп на экране — как в макете. */
export const KIND_ORDER = ['no_audio', 'no_cover', 'video_missing', 'encoding', 'duplicate', 'diverged'];

export const FIXED_JOB = 'Исправление поставлено'; // исправление ушло в очередь
export const FIXED_DONE = 'Исправлено'; // исправлено сразу

function plural(n, one, few, many) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

/** Группы непустых видов находок: [{kind, label, count, findings}]. */
export function groupFindings(report) {
  const list = Array.isArray(report?.findings) ? report.findings : [];
  return KIND_ORDER
    .map((kind) => {
      const findings = list.filter((f) => f.kind === kind);
      return { kind, label: KIND_LABELS[kind], count: findings.length, findings };
    })
    .filter((g) => g.count);
}

/** Счётчик в заголовке группы: у дублей — пары. */
export function countLabel(kind, n) {
  return kind === 'duplicate' ? `${n} ${plural(n, 'пара', 'пары', 'пар')}` : String(n);
}

function targetName(targets, id) {
  const t = (targets || []).find((x) => x.id === id);
  return t?.name || t?.label || id;
}

function buttonLabel(fix, finding, targets) {
  switch (fix.action) {
    case 'copy_from': return `Взять из копии в «${targetName(targets, fix.from_target)}»`;
    case 'audio_from_video': return 'Скачать звук по ссылке #VIDEO';
    case 'trash': return 'В корзину';
    case 'cover_search': return 'Найти обложку…';
    case 'video_remove': return 'Убрать ссылку';
    case 'encoding': return 'Исправить кодировку';
    case 'keep_this': return fix.song_id === finding.song_id ? 'Оставить эту' : 'Оставить другую';
    case 'make_like': return `Сделать как в «${targetName(targets, fix.from_target)}»`;
    default: return fix.action;
  }
}

/** Кнопки исправлений находки: [{label, action, fix, danger, disabled}] (первая — основная). */
export function fixButtons(finding, targets) {
  const fixes = finding.fixes?.length ? finding.fixes : (finding.fix ? [finding.fix] : []);
  return fixes.map((fix) => ({
    label: buttonLabel(fix, finding, targets),
    action: fix.action,
    fix,
    danger: fix.action === 'trash',
    disabled: fix.disabled || false,
  }));
}

const who = (f) => `«${f.artist} — ${f.title}»`;

/**
 * Что вызвать для исправления: {method, args, mark, confirm?}.
 * method — имя метода `api` (или 'cover' — диалог обложки); mark — подпись строки после успеха
 * (null — строку не помечаем); confirm — вопрос перед действием.
 */
export function fixCall(fix, finding) {
  switch (fix.action) {
    case 'copy_from':
    case 'make_like':
      return {
        method: 'copySongs',
        args: [{ song_ids: [fix.from_song_id], target_id: finding.target_id, replace: true, only_missing: false }],
        mark: FIXED_JOB,
      };
    case 'audio_from_video':
      return { method: 'audioFromVideo', args: [finding.song_id], mark: FIXED_JOB };
    case 'trash':
      return {
        method: 'bulkDelete', args: [[finding.song_id]], mark: FIXED_DONE,
        confirm: { text: `Убрать песню ${who(finding)} в корзину?`, ok: 'В корзину' },
      };
    case 'keep_this': {
      const other = finding.other && finding.other.song_id === fix.trash_song_id ? finding.other : finding;
      return {
        method: 'bulkDelete', args: [[fix.trash_song_id]], mark: FIXED_DONE,
        confirm: { text: `Убрать ${who(other)} (${other.rel_dir || 'копия'}) в корзину и оставить вторую?`, ok: 'В корзину' },
      };
    }
    case 'video_remove':
      return { method: 'video', args: [finding.song_id, { remove: true }], mark: FIXED_JOB };
    case 'encoding':
      return { method: 'fixEncoding', args: [finding.song_id], mark: FIXED_DONE };
    case 'cover_search':
      return { method: 'cover', args: [], mark: null };
    default:
      return null;
  }
}

/** Строки про пропущенные (недоступные) хранилища. */
export function skippedLines(report) {
  return (report?.skipped || []).map((s) =>
    `Хранилище «${s.name || s.target_id}» недоступно — пропущено${s.error ? `: ${s.error}` : ''}`);
}

/** Прогресс идущей проверки: этап и процент. */
export function progressLine(job) {
  if (!job || job.state === 'queued') return 'Ожидает запуска';
  const pct = Math.max(0, Math.min(100, Math.round(job.percent || 0)));
  return [job.stage, `${pct}%`].filter(Boolean).join(' · ');
}

/** «Последняя проверка: …» (fmt — форматтер даты); до первой проверки пусто. */
export function checkedLine(report, fmt) {
  if (!Array.isArray(report?.findings) || !report.finished_at) return '';
  return `Последняя проверка: ${fmt(report.finished_at)}`;
}
