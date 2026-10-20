// Общие помощники api.js: параметры генерации, multipart для generate, текст ошибки.
import test from 'node:test';
import assert from 'node:assert/strict';
import { PARAM_KEYS, pickParams, generateForm, errorText, ApiError } from '../../web/static/js/api.js';

test('PARAM_KEYS и pickParams: только известные ключи, undefined отбрасывается', () => {
  assert.deepEqual(PARAM_KEYS, ['whisper_model', 'language', 'compute_type', 'batch_size', 'align_model',
    'vad_onset', 'vad_offset', 'demucs_model', 'keep_debug']);
  assert.deepEqual(pickParams({ whisper_model: 'm', rel_dir: 'x', language: undefined, vad_onset: null }),
    { whisper_model: 'm', vad_onset: null });
});

test('generateForm: поля multipart как ждёт POST /api/jobs/generate', () => {
  const audio = new Blob([new Uint8Array([0xff, 0xfb])], { type: 'audio/mpeg' });
  const fd = generateForm({ artist: 'A', title: 'T', lyrics: 'x', audio, params: { language: 'ru', junk: 1 },
    song_id: 's1', replace: true });
  assert.equal(fd.get('artist'), 'A');
  assert.equal(fd.get('title'), 'T');
  assert.equal(fd.get('lyrics'), 'x');
  assert.equal(fd.get('song_id'), 's1');
  assert.equal(fd.get('replace'), 'true');
  assert.deepEqual(JSON.parse(fd.get('params')), { language: 'ru' });
  assert.ok(fd.get('audio') instanceof Blob);
  assert.equal(fd.has('cover'), false);
  const plain = generateForm({ artist: 'A', title: 'T', lyrics: '', params: {} });
  assert.equal(plain.get('replace'), 'false');
  assert.equal(plain.has('song_id'), false);
  assert.equal(plain.has('audio'), false);
});

test('errorText: detail сервера, иначе message, иначе запасной текст', () => {
  assert.equal(errorText(new ApiError(400, 'Плохо')), 'Плохо');
  assert.equal(errorText(new Error('boom')), 'boom');
  assert.equal(errorText({}, 'Запас'), 'Запас');
  assert.equal(errorText(null), 'Ошибка');
});
