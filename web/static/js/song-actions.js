// Действия с песней — общие для списка «Песен» (меню «…») и страницы песни:
// перегенерация, минусовка, видео, zip, «Копировать в…», редакторы, теги, удаление.
//
// env = {targets, currentTargetId, outputOk, trashDays, reload, afterRemove?, tags?}
//   targets — [{id, name|label}] всех хранилищ; currentTargetId — хранилище песни;
//   reload() — перечитать то, что на экране; afterRemove() — после удаления (иначе reload).

import { api, getDefaults, errorText, probeDownload, JOB_FINAL } from './api.js';
import { h, confirmDialog, runAction, toast, days, songName } from './ui.js';
import { createVideoBlock } from './video-block.js';
import { songEditors } from './extensions.js';
import { openTagsDialog } from './tags-ui.js';

const WATCH_MS = 3000;
const watched = new Set();
const UNAVAILABLE = 'Хранилище недоступно — действия с файлами отключены';
const NO_AUDIO = 'У песни нет аудиофайла';
const NO_OTHERS = 'Других хранилищ нет — добавьте их в «Настройках»';

const targetName = (t) => t?.name || t?.label || '';
const otherTargets = (env) => (env.targets || []).filter((t) => t.id !== env.currentTargetId);

/** Следить за заданием: дошло до конца (done/failed/cancelled) — onFinal(job). */
export function watchJob(job, onFinal) {
  if (!job?.id || watched.has(job.id)) return;
  watched.add(job.id);
  const tick = async () => {
    try {
      const j = await api.job(job.id);
      if (JOB_FINAL.includes(j.state)) {
        watched.delete(job.id);
        onFinal?.(j);
        return;
      }
    } catch (e) {
      if (e?.status === 404) { watched.delete(job.id); return; } // задание удалено
    }
    setTimeout(tick, WATCH_MS);
  };
  setTimeout(tick, WATCH_MS);
}

export function regenerateHref(song) {
  return `#new?song=${encodeURIComponent(song.song_id)}`;
}

/** Пункты меню «…» песни; editors: false — без редакторов (на странице они отдельными кнопками). */
export function songMenuItems(song, env, { editors = true } = {}) {
  const off = env.outputOk === false ? UNAVAILABLE : false;
  const others = otherTargets(env);
  const items = [
    { label: 'Перегенерировать', href: regenerateHref(song), disabled: off },
    { label: song.instrumental ? 'Пересоздать минусовку' : 'Минусовка', disabled: off || (song.audio ? false : NO_AUDIO),
      onSelect: () => makeInstrumental(null, song, env) },
    { label: 'Видео…', disabled: off, onSelect: () => openVideoDialog(song, env) },
    { label: 'Скачать .zip', href: api.zipUrl(song.song_id), download: true, disabled: off,
      onSelect: (e) => { e.preventDefault(); downloadZip(song); } },
    { label: 'Копировать в…', disabled: off || (others.length ? false : NO_OTHERS),
      onSelect: () => openCopyDialog([song], env) },
  ];
  if (editors) items.push(...editorItems(song, env));
  items.push(
    { label: 'Теги…', onSelect: () => openSongTagsDialog(song, env) },
    'sep',
    { label: 'Удалить', danger: true, disabled: off, onSelect: () => removeSong(null, song, env) },
  );
  return items;
}

/** Редакторы песни (extensions.js) пунктами меню или кнопками: {label, disabled, open()}. */
export function editorItems(song, env) {
  return songEditors().map((ed) => {
    const st = ed.enabled ? ed.enabled(song) : true;
    const reason = env.outputOk === false ? UNAVAILABLE : st === true ? false : (typeof st === 'string' ? st : 'Недоступно');
    const open = () => ed.open(song, { reload: env.reload });
    return { kind: ed.kind, label: ed.label, disabled: reason, onSelect: open, open };
  });
}

/** «Скачать .zip»: сначала `?check=1` (503/404 — тост вместо битого архива), потом одно скачивание. */
export async function downloadZip(song) {
  const url = api.zipUrl(song.song_id);
  try {
    await probeDownload(`${url}?check=1`); // лёгкая проверка: файлы не читаются, поток один
    const a = h('a', { href: url, download: '' });
    document.body.append(a);
    a.click();
    a.remove();
  } catch (err) {
    toast(`Не удалось скачать «${songName(song.artist, song.title)}»: ${err.detail || err.message}`, 'err');
  }
}

export async function removeSong(btn, song, env) {
  const name = songName(song.artist, song.title);
  const term = env.trashDays == null ? 'Песня уйдёт в корзину' : `Песня уйдёт в корзину на ${days(env.trashDays)}`;
  if (!(await confirmDialog(`Удалить "${name}"? ${term}`, 'Удалить', { danger: true }))) return;
  const res = await runAction(btn, () => api.deleteSong(song.song_id), `«${name}» перемещена в корзину`);
  if (res) (env.afterRemove || env.reload)?.();
}

export async function makeInstrumental(btn, song, env) {
  const name = songName(song.artist, song.title);
  if (song.instrumental
    && !(await confirmDialog(`Пересоздать минусовку для "${name}"? Старый файл уйдёт в корзину.`, 'Пересоздать'))) return;
  watchJob(await runAction(btn, () => api.instrumental(song.song_id, !!song.instrumental), 'Минусовка поставлена в очередь'),
    () => env.reload?.());
}

export function openSongTagsDialog(song, env) {
  return openTagsDialog(song, { onSaved: () => env.reload?.() });
}

/** Диалог «Копировать в…»: хранилище (кроме текущего), «если уже есть», у «показанных» — «только недостающие». */
export function openCopyDialog(songs, env, { bulk = false } = {}) {
  const others = otherTargets(env);
  if (!songs.length || !others.length) return;
  const title = bulk ? `Копировать показанные (${songs.length}) в…`
    : `Копировать «${songName(songs[0].artist, songs[0].title)}» в…`;
  const radios = others.map((t, i) => h('label', { class: 'check' },
    h('input', { type: 'radio', name: 'copy-target', value: t.id, checked: i === 0 }), targetName(t)));
  const repl = h('input', { type: 'radio', name: 'copy-exists', value: 'replace' });
  const onlyMissing = bulk ? h('input', { type: 'checkbox', name: 'only-missing', checked: true }) : null;
  const errEl = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  const submit = h('button', { type: 'button', class: 'primary' }, 'Копировать');
  const cancel = h('button', { type: 'button', onclick: () => el.close() }, 'Отмена');
  const existsBox = h('fieldset', {}, h('legend', {}, 'Если песня там уже есть'),
    h('label', { class: 'check' }, h('input', { type: 'radio', name: 'copy-exists', value: 'skip', checked: true }), 'пропустить'),
    h('label', { class: 'check' }, repl, 'заменить (прежняя версия уйдёт в корзину)'));
  const el = h('dialog', { class: 'copy-dlg', 'aria-labelledby': 'copy-dlg-title' },
    h('h3', { id: 'copy-dlg-title' }, title),
    h('fieldset', {}, h('legend', {}, 'Хранилище'), radios),
    bulk ? h('label', { class: 'check' }, onlyMissing, 'только недостающие') : null,
    existsBox, errEl,
    h('div', { class: 'actions' }, cancel, submit));
  // «только недостающие» — уже имеющиеся пропускаются, выбор «заменить» не нужен
  const syncExists = () => { existsBox.disabled = !!onlyMissing?.checked; };
  onlyMissing?.addEventListener('change', syncExists);
  syncExists();
  el.addEventListener('close', () => el.remove());
  document.body.append(el);
  if (typeof el.showModal === 'function') el.showModal(); else el.setAttribute('open', '');

  submit.addEventListener('click', async () => {
    const to = el.querySelector('input[name="copy-target"]:checked')?.value;
    const toName = targetName(others.find((t) => t.id === to));
    const replace = !onlyMissing?.checked && repl.checked;
    const body = { song_ids: songs.map((s) => s.song_id), target_id: to, replace,
      only_missing: bulk ? onlyMissing.checked : !replace };
    errEl.hidden = true;
    submit.disabled = true;
    try {
      const res = await api.copySongs(body);
      el.close();
      const n = res.queued.length;
      const errs = res.errors?.length ? `; не скопировано ${res.errors.length}: ${res.errors[0].detail}` : '';
      if (bulk) toast(`В «${toName}»: поставлено ${n}, пропущено ${res.skipped} (уже есть)${errs}`, errs ? 'err' : '');
      else if (n) toast(`Копирование в «${toName}» поставлено в очередь`);
      else if (res.skipped) toast(`Уже есть в «${toName}» — пропущено`);
      else toast(`Не скопировано${errs}`, 'err');
      env.reload?.(); // пометка «ждёт копирования»
    } catch (e) {
      errEl.textContent = errorText(e);
      errEl.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
}

/** Текущее #VIDEOGAP песни (из заголовков GET /notes); нет или ошибка — ''. */
async function currentVideoGap(song) {
  try {
    const { headers = [] } = await api.notes(song.song_id);
    const hit = headers.find(([k]) => String(k).toUpperCase() === 'VIDEOGAP');
    return hit ? String(hit[1]).trim().replace(',', '.') : '0';
  } catch {
    return null; // не узнали — смещение не отправляется, чтобы не стереть #VIDEOGAP
  }
}

/** Диалог «Видео…»: своя ссылка с качеством или файл, смещение; у песни с видео — «Убрать видео». */
export async function openVideoDialog(song, env) {
  const name = songName(song.artist, song.title);
  let d = {};
  try { d = await getDefaults(); } catch { /* умолчания блока */ }
  const block = createVideoBlock({ modes: ['url', 'file'], mode: 'url', gap: '0', maxMb: d.max_video_mb,
    heights: d.video_heights, defaultHeight: d.default_video_height, exts: d.video_exts });
  let gapKnown = false; // текущее смещение песни прочитано (иначе без правки videogap не уходит)
  const errEl = h('div', { class: 'banner err', hidden: true, role: 'alert' });
  const submit = h('button', { type: 'button', class: 'primary' }, song.video ? 'Заменить видео' : 'Прикрепить');
  const cancel = h('button', { type: 'button', onclick: () => el.close() }, 'Отмена');
  const removeBtn = song.video
    ? h('button', { type: 'button', class: 'danger', onclick: () => removeVideo() }, 'Убрать видео') : null;
  const el = h('dialog', { class: 'video-dlg', 'aria-labelledby': 'video-dlg-title' },
    h('h3', { id: 'video-dlg-title' }, `Видео: ${name}`),
    song.video ? h('div', { class: 'banner warn' },
      `У песни уже есть видео «${song.video}». При замене старое видео удалится.`) : null,
    block.el, errEl,
    h('div', { class: 'actions' }, removeBtn, h('span', { class: 'spacer' }), cancel, submit));
  el.addEventListener('close', () => el.remove());
  document.body.append(el);
  if (typeof el.showModal === 'function') el.showModal(); else el.setAttribute('open', '');
  currentVideoGap(song).then((gap) => {
    if (gap === null) return;
    gapKnown = true;
    if (!block.state().gapTouched) block.setGap(gap);
  });

  async function send(form, okText) {
    errEl.hidden = true;
    for (const b of [submit, removeBtn]) if (b) b.disabled = true;
    try {
      const job = await api.video(song.song_id, form);
      el.close();
      watchJob(job, () => env.reload?.()); // метка «видео» обновится сама
      toast(okText);
    } catch (e) {
      if (!block.showApiError(e)) {
        errEl.textContent = errorText(e);
        errEl.hidden = false;
      }
    } finally {
      for (const b of [submit, removeBtn]) if (b) b.disabled = false;
    }
  }

  submit.addEventListener('click', () => {
    if (!block.validate()) return;
    const fields = block.fields();
    if (!gapKnown && !block.state().gapTouched) delete fields.videogap;
    send(fields, 'Видео поставлено в очередь');
  });

  async function removeVideo() {
    if (!(await confirmDialog(`Убрать видео у "${name}"? Файл видео удалится, а #VIDEO и #VIDEOGAP уйдут из .txt.`,
      'Убрать', { danger: true }))) return;
    send({ remove: true }, 'Удаление видео поставлено в очередь');
  }
}
