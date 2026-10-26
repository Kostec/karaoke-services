// Чистая логика диалога «Переименовать…»: проверка полей, тело POST /api/jobs/rename,
// новый song_id своей копии из ответа. Тексты ошибок — как у сервера (web/app/api_jobs.py).

const clean = (s) => String(s ?? '').trim();

/** Ошибки ввода: {artist?, title?} (пусто — можно отправлять). */
export function renameErrors({ artist, title } = {}, song = {}) {
  const a = clean(artist);
  const t = clean(title);
  const errs = {};
  if (!a) errs.artist = 'Введите исполнителя';
  if (!t) errs.title = 'Введите название';
  if (a && t && a === clean(song.artist) && t === clean(song.title)) errs.title = 'Имя не изменилось';
  return errs;
}

/** Тело запроса: {song_id, artist, title} без пробелов по краям. */
export function renameBody(song, { artist, title } = {}) {
  return { song_id: song.song_id, artist: clean(artist), title: clean(title) };
}

/** Задание и новый song_id копии в хранилище targetId из ответа {jobs:[{job_id, target_id, song_id}]}. */
export function ownRename(res, targetId) {
  const jobs = res?.jobs || [];
  return jobs.find((j) => j.target_id === targetId) || jobs[0] || null;
}
