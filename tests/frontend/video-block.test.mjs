// Блок «Видео» (video-block.js): чистая сборка полей multipart, проверка, память качества;
// api.js::videoForm — multipart для POST /api/jobs/video.
import test from 'node:test';
import assert from 'node:assert/strict';
import { videoFields, videoError, normGap, rememberedHeight, rememberHeight, VIDEO_MODES } from '../../web/static/js/video-block.js';
import { videoForm } from '../../web/static/js/api.js';

const file = new Blob([new Uint8Array([1, 2])], { type: 'video/mp4' });

test('VIDEO_MODES — все режимы из спецификации', () => {
  assert.deepEqual(VIDEO_MODES, ['none', 'source', 'url', 'file', 'pack']);
});

test('videoFields: без видео — только режим', () => {
  assert.deepEqual(videoFields({ mode: 'none', url: 'https://x', height: 480, gap: '1' }), { video_mode: 'none' });
  assert.deepEqual(videoFields({}), { video_mode: 'none' });
});

test('videoFields: своя ссылка — ссылка, качество, смещение', () => {
  assert.deepEqual(videoFields({ mode: 'url', url: '  https://youtu.be/a  ', height: 0, gap: '-1,25', file }),
    { video_mode: 'url', video_url: 'https://youtu.be/a', video_height: '0', videogap: '-1.25' });
});

test('videoFields: файл — без качества и ссылки', () => {
  const f = videoFields({ mode: 'file', file, url: 'https://x', height: 720, gap: '0' });
  assert.deepEqual(Object.keys(f).sort(), ['video_file', 'video_mode', 'videogap']);
  assert.equal(f.video_file, file);
  assert.equal(f.videogap, '0');
});

test('videoFields: из ссылки песни — качество; из архива — только смещение; пустое смещение не уходит', () => {
  assert.deepEqual(videoFields({ mode: 'source', height: 1080, gap: '' }), { video_mode: 'source', video_height: '1080' });
  assert.deepEqual(videoFields({ mode: 'pack', height: 1080, gap: ' 2.5 ' }), { video_mode: 'pack', videogap: '2.5' });
});

test('normGap: запятая — точка, пробелы срезаются', () => {
  assert.equal(normGap(' 1,5 '), '1.5');
  assert.equal(normGap(''), '');
  assert.equal(normGap(undefined), '');
  assert.equal(normGap(-2), '-2');
});

test('videoError: пустая ссылка, нет файла, не число в смещении', () => {
  assert.deepEqual(videoError({ mode: 'url', url: ' ' }), { field: 'video_url', text: 'Вставьте ссылку на видео' });
  assert.deepEqual(videoError({ mode: 'file' }), { field: 'video', text: 'Выберите видеофайл' });
  assert.deepEqual(videoError({ mode: 'url', url: 'https://x', gap: '1.2.3' }),
    { field: 'videogap', text: 'Смещение видео — число секунд, например 1.5 или -0.25' });
  assert.equal(videoError({ mode: 'url', url: 'https://x', gap: '-0,5' }), null);
  assert.equal(videoError({ mode: 'none', gap: 'abc' }), null);
});

test('rememberedHeight/rememberHeight: localStorage video.height, чужое значение и сбой — умолчание', () => {
  const heights = [360, 480, 720, 1080, 0];
  const store = new Map();
  const ls = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
  assert.equal(rememberedHeight(heights, 720, ls), 720);
  rememberHeight(0, ls);
  assert.equal(store.get('video.height'), '0');
  assert.equal(rememberedHeight(heights, 720, ls), 0);
  store.set('video.height', '999');
  assert.equal(rememberedHeight(heights, 720, ls), 720);
  const broken = { getItem: () => { throw new Error('нет'); }, setItem: () => { throw new Error('нет'); } };
  assert.equal(rememberedHeight(heights, 480, broken), 480);
  assert.doesNotThrow(() => rememberHeight(360, broken));
});

test('videoForm: поля POST /api/jobs/video', () => {
  const byUrl = videoForm('s1', videoFields({ mode: 'url', url: 'https://youtu.be/a', height: 720, gap: '1.5' }));
  assert.equal(byUrl.get('song_id'), 's1');
  assert.equal(byUrl.get('video_url'), 'https://youtu.be/a');
  assert.equal(byUrl.get('video_height'), '720');
  assert.equal(byUrl.get('videogap'), '1.5');
  assert.equal(byUrl.has('video'), false);
  assert.equal(byUrl.has('video_mode'), false);
  assert.equal(byUrl.has('remove'), false);
  const byFile = videoForm('s1', videoFields({ mode: 'file', file, gap: '0' }));
  assert.ok(byFile.get('video') instanceof Blob);
  assert.equal(byFile.has('video_url'), false);
  const rm = videoForm('s1', { remove: true });
  assert.equal(rm.get('remove'), 'true');
  assert.deepEqual([...rm.keys()].sort(), ['remove', 'song_id']);
});
