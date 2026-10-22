// Модель редактора нот (спека §2–§5, §14, §15): чистые функции web/static/js/editors/notes-model.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/static/js/editors/notes-model.js';

let nid = 0;
const n = (start, length, text, pitch = 5, type = ':') => ({ id: nid++, type, start, length, pitch, text });

// Ответ GET /notes: три строки, разрывы «- 10» и «- 22» (разрыв 10 — с запасом после конца ноты 8).
function payload() {
  nid = 0;
  return {
    editable: true, bpm: 300, gap: 1000, headers: [['TITLE', 'T'], ['BPM', '300']],
    lines: [
      { break_beat: 10, notes: [n(0, 2, 'Hel'), n(2, 3, 'lo'), n(6, 2, ' world')] },
      { break_beat: 22, notes: [n(12, 4, 'Sec'), n(16, 2, 'ond')] },
      { break_beat: null, notes: [n(24, 4, 'Last', 7, '*')] },
    ],
  };
}
const body = (data) => ({ gap: data.gap, lines: data.lines });
const texts = (st) => M.lines(st).map((l) => l.map((x) => x.text));
const byText = (st, t) => st.notes.find((x) => x.text === t);

test('загрузка и выгрузка без правок дают исходное тело PUT', () => {
  const data = payload();
  assert.deepEqual(M.toPayload(M.fromPayload(data)), body(payload()));
  assert.deepEqual(data, payload(), 'ответ сервера не меняется');
});

test('перемещение: по битам и полутонам, обгон соседа меняет порядок, слог едет с нотой', () => {
  const st = M.fromPayload(payload());
  const lo = byText(st, 'lo').id;
  const out = M.move(st, [lo], 0, 2);
  assert.deepEqual(M.toPayload(out).lines[0].notes[1], { id: 1, type: ':', start: 2, length: 3, pitch: 7, text: 'lo' });
  assert.equal(byText(st, 'lo').pitch, 5, 'исходное состояние не меняется');
  // «lo» (2..5) уезжает на 7: обгоняет « world» (6)
  const over = M.move(st, [lo], 5, 0);
  assert.deepEqual(texts(over), [['Hel', ' world', 'lo'], ['Sec', 'ond'], ['Last']]);
  assert.equal(byText(over, 'lo').start, 7);
  // нота-начало строки уезжает за следующую: флаг строки остаётся у неё, «ond» переходит в прежнюю строку
  const sec = byText(st, 'Sec').id;
  assert.deepEqual(texts(M.move(st, [sec], 6, 0)), [['Hel', 'lo', ' world', 'ond'], ['Sec'], ['Last']]);
});

test('высота вне −40…100 — ошибка, состояние не меняется', () => {
  const st = M.fromPayload(payload());
  const last = byText(st, 'Last').id;
  assert.throws(() => M.move(st, [last], 0, 94), /Высота ноты — от −40 до 100/);
  assert.throws(() => M.move(st, [last], 0, -48), /Высота ноты — от −40 до 100/);
  assert.equal(M.move(st, [last], 0, 93).notes.at(-1).pitch, 100);
});

test('сдвиг всех нот левее бита 0 уходит в gap, время звучания сохраняется (§5)', () => {
  const st = M.fromPayload(payload());
  const all = st.notes.map((x) => x.id);
  // BPM 300: бит = 50 мс; сдвиг на −4 бита → gap 1000 − 200 = 800, первая нота на бите 0
  const out = M.move(st, all, -4, 0);
  assert.equal(out.gap, 800);
  assert.deepEqual(out.notes.map((x) => x.start), [0, 2, 6, 12, 16, 24]);
  const body = M.toPayload(out);
  assert.equal(body.gap, 800);
  assert.deepEqual(body.lines.map((l) => l.break_beat), [10, 22, null]);
  // gap 1000 мс = 20 бит: на 21 бит раньше — некуда
  assert.throws(() => M.move(st, all, -21, 0), /Раньше начала трека сдвигать некуда/);
  assert.equal(M.move(st, all, -20, 0).gap, 0);
  // сдвиг вправо gap не трогает
  assert.equal(M.move(st, all, 3, 0).gap, 1000);
});

test('растяжение за правый и левый край, минимум 1 бит', () => {
  const st = M.fromPayload(payload());
  const lo = byText(st, 'lo').id; // 2..5
  const r = byText(M.resize(st, lo, 'right', 2), 'lo');
  assert.deepEqual([r.start, r.length], [2, 5]);
  const l = byText(M.resize(st, lo, 'left', -1), 'lo');
  assert.deepEqual([l.start, l.length], [1, 4]);
  const l2 = byText(M.resize(st, lo, 'left', 2), 'lo');
  assert.deepEqual([l2.start, l2.length], [4, 1]);
  // короче 1 бита не бывает: конец остаётся на месте, левый край упирается
  const min = byText(M.resize(st, lo, 'left', 10), 'lo');
  assert.deepEqual([min.start, min.length], [4, 1]);
  assert.equal(byText(M.resize(st, lo, 'right', -10), 'lo').length, 1);
  assert.throws(() => M.resize(st, lo, 'middle', 1), /край/);
});

test('добавление ноты: встаёт по времени, новая — id null в теле PUT, создана в created', () => {
  const st = M.fromPayload(payload());
  const out = M.addNote(st, { start: 9, pitch: 3 });
  assert.equal(out.created.length, 1);
  const added = out.notes.find((x) => x.id === out.created[0]);
  assert.deepEqual([added.start, added.length, added.pitch, added.text, added.type, added.ls], [9, 4, 3, '', ':', false]);
  assert.ok(!st.notes.some((x) => x.id === added.id), 'id новой ноты не совпадает с прежними');
  const body = M.toPayload(out);
  assert.deepEqual(body.lines[0].notes.at(-1), { id: null, type: ':', start: 9, length: 4, pitch: 3, text: '' });
  // разрыв 10 оказался внутри новой ноты (9..13) — разрыв теперь её конец
  assert.equal(body.lines[0].break_beat, 13);
  assert.equal(M.addNote(st, { start: 30, pitch: 0, length: 3 }).notes.at(-1).length, 3);
  assert.throws(() => M.addNote(st, { start: 30, pitch: 101 }), /Высота ноты — от −40 до 100/);
});

test('удаление: начало строки передаётся следующей ноте, последнюю ноту удалить нельзя', () => {
  const st = M.fromPayload(payload());
  const sec = byText(st, 'Sec').id;
  const out = M.deleteNotes(st, [sec]);
  assert.deepEqual(texts(out), [['Hel', 'lo', ' world'], ['ond'], ['Last']]);
  // удалена строка целиком
  assert.deepEqual(texts(M.deleteNotes(st, [sec, byText(st, 'ond').id])), [['Hel', 'lo', ' world'], ['Last']]);
  // удалена первая нота песни — строку начинает следующая
  assert.deepEqual(texts(M.deleteNotes(st, [byText(st, 'Hel').id]))[0], ['lo', ' world']);
  assert.throws(() => M.deleteNotes(st, st.notes.map((x) => x.id)), /хотя бы одна нота/);
});

test('текст слога: меняется только он; перевод строки — ошибка', () => {
  const st = M.fromPayload(payload());
  const lo = byText(st, 'lo').id;
  const out = M.setText(st, lo, ' LO');
  assert.deepEqual(texts(out)[0], ['Hel', ' LO', ' world']);
  assert.deepEqual(M.toPayload(out).lines.slice(1), M.toPayload(st).lines.slice(1));
  assert.throws(() => M.setText(st, lo, 'a\nb'), /перевод/i);
});

test('строка целиком раскладывается по нотам: лишние ноты — «~», лишние слоги — в последнюю ноту', () => {
  const st = M.fromPayload(payload());
  assert.deepEqual(texts(M.setLineText(st, 0, 'мо|ло ко'))[0], ['мо', 'ло', ' ко']);
  assert.deepEqual(texts(M.setLineText(st, 0, 'да'))[0], ['да', '~', '~']);
  assert.deepEqual(texts(M.setLineText(st, 1, 'ма ма мы ла'))[1], ['ма', ' ма мы ла']);
  // «~» из текста панели не считается слогом
  assert.deepEqual(texts(M.setLineText(st, 0, 'да~ ~'))[0], ['да', '~', '~']);
  assert.deepEqual(texts(M.setLineText(st, 2, 'Last'))[2], ['Last']);
  assert.equal(M.lineText(M.lines(M.setLineText(st, 0, 'да'))[0]), 'да');
  assert.equal(M.lineText(M.lines(st)[0]), 'Hello world');
});

test('«+ K нот»: по 3 бита подряд за последней нотой строки, с её высотой, остаются в строке', () => {
  const st = M.fromPayload(payload());
  const out = M.addNotesToLine(st, 1, 3); // строка 2 кончается на 18, следующая — с 24
  const line = M.lines(out)[1];
  assert.deepEqual(line.map((x) => [x.start, x.length, x.pitch]), [[12, 4, 5], [16, 2, 5], [18, 3, 5], [21, 3, 5], [24, 3, 5]]);
  assert.equal(out.created.length, 3);
  assert.deepEqual(texts(out)[2], ['Last']);
  // последняя добавленная упирается в следующую строку — перекрытие
  assert.deepEqual([...M.overlaps(out)].sort(), [out.created[2], byText(st, 'Last').id].sort());
});

test('сдвиг текста по нотам строки: вправо и влево, отказ, когда некуда', () => {
  const st = M.setText(M.fromPayload(payload()), 2, '~'); // строка 1: Hel lo ~
  const lo = byText(st, 'lo').id;
  const right = M.shiftText(st, lo, 1);
  assert.deepEqual(texts(right)[0], ['Hel', '~', 'lo']);
  const back = M.shiftText(right, byText(right, 'lo').id, -1);
  assert.deepEqual(texts(back)[0], ['Hel', 'lo', '~']);
  const hel = byText(st, 'Hel').id;
  assert.deepEqual(texts(M.shiftText(st, hel, 1))[0], ['~', 'Hel', 'lo']);
  // справа занято: последний слог строки приклеивается к последней ноте (текст не теряется)
  const full = M.fromPayload(payload());
  assert.deepEqual(texts(M.shiftText(full, lo, 1)), [['Hel', '~', 'lo world'], ['Sec', 'ond'], ['Last']]);
  // слева занято: слог приклеивается к предыдущей ноте, последняя нота строки получает «~»
  assert.deepEqual(texts(M.shiftText(full, lo, -1))[0], ['Hello', ' world', '~']);
  // первая нота строки — левее в строке нот нет
  assert.throws(() => M.shiftText(st, hel, -1), /Левее в этой строке нот нет/);
});

test('shiftTextBy: область «песня» — через границы строк, ноты и строки не двигаются', () => {
  const st = M.fromPayload(payload()); // [Hel lo ␣world] [Sec ond] [Last]
  const world = byText(st, ' world').id;
  const right = M.shiftTextBy(st, world, 2, 'song');
  assert.deepEqual(texts(right), [['Hel', 'lo', '~'], ['~', ' world'], ['SecondLast']]);
  assert.deepEqual(right.notes.map((x) => [x.start, x.length, x.ls]), st.notes.map((x) => [x.start, x.length, x.ls]));
  const left = M.shiftTextBy(st, byText(st, 'Sec').id, -1, 'song');
  assert.deepEqual(texts(left), [['Hel', 'lo', ' worldSec'], ['ond', 'Last'], ['~']]);
  assert.throws(() => M.shiftTextBy(st, byText(st, 'Hel').id, -1, 'song'), /Левее нот нет/);
  assert.deepEqual(texts(st), [['Hel', 'lo', ' world'], ['Sec', 'ond'], ['Last']], 'вход не меняется');
});

test('shiftTextBy: область «слово» — до пробела-границы слова, соседние слова не трогаются', () => {
  const st = M.fromPayload(payload());
  const hel = byText(st, 'Hel').id;
  const lo = byText(st, 'lo').id;
  const world = byText(st, ' world').id;
  assert.deepEqual(texts(M.shiftTextBy(st, hel, 1, 'word'))[0], ['~', 'Hello', ' world']);
  assert.deepEqual(texts(M.shiftTextBy(st, lo, -1, 'word'))[0], ['Hello', '~', ' world']);
  assert.throws(() => M.shiftTextBy(st, world, -1, 'word'), /Левее в этом слове нот нет/);
  // UltraSinger: граница слова — пробел в конце слога; «~ » свободна и не теряет пробел
  const us = M.fromPayload(usPayload()); // In|to␣|my|~␣|eyes␣
  const my = byText(us, 'my').id;
  assert.deepEqual(texts(M.shiftTextBy(us, my, 1, 'word'))[0], ['In', 'to ', '~', 'my ', 'eyes ']);
  assert.deepEqual(texts(M.shiftTextBy(us, us.notes[3].id, -1, 'word'))[0], ['In', 'to ', 'my ', '~', 'eyes ']);
});

test('shiftTextBy: сдвиг на несколько нот; влево дальше начала области — до её начала', () => {
  const st = M.fromPayload(payload());
  const hel = byText(st, 'Hel').id;
  assert.deepEqual(texts(M.shiftTextBy(st, hel, 2, 'line'))[0], ['~', '~', 'Hello world']);
  const world = byText(st, ' world').id;
  assert.deepEqual(texts(M.shiftTextBy(st, world, -2, 'line'))[0], ['Hello world', '~', '~']);
  assert.deepEqual(texts(M.shiftTextBy(st, world, -5, 'line'))[0], ['Hello world', '~', '~']);
  assert.throws(() => M.shiftTextBy(st, 99, 1, 'line'), { message: 'Нет такой ноты' });
  // фактический сдвиг (для подсказки перетаскивания) — из той же модели
  assert.equal(M.shiftAmount(st, world, -5, 'line'), -2);
  assert.equal(M.shiftAmount(st, hel, 9, 'word'), 1);
});

test('shiftTextBy: отказ вправо у последней ноты области; неизвестная область', () => {
  const st = M.fromPayload(payload());
  assert.throws(() => M.shiftTextBy(st, byText(st, ' world').id, 1, 'line'), /Правее в этой строке нот нет/);
  assert.throws(() => M.shiftTextBy(st, byText(st, 'lo').id, 1, 'word'), /Правее в этом слове нот нет/);
  assert.throws(() => M.shiftTextBy(st, byText(st, 'Last').id, 1, 'song'), /Правее нот нет/);
  assert.throws(() => M.shiftRange(st, 0, 'verse'), /Неизвестная область/);
  assert.throws(() => M.shiftTextBy(st, 0, 1, 'verse'), /Неизвестная область/);
});

test('область «слово»: нота «~» (с пробелами) — продолжение предыдущего слова', () => {
  const us = M.fromPayload(usPayload()); // In|to␣|my|~␣|eyes␣
  const tilde = M.setText(us, 2, '~ '); // In|to␣|~␣|~␣|eyes␣ — «to» протянуто на две ноты
  assert.deepEqual(M.shiftRange(tilde, 2, 'word'), { first: 0, last: 3 });
  assert.deepEqual(M.shiftRange(tilde, 4, 'word'), { first: 4, last: 4 });
  assert.deepEqual(M.shiftRange(us, 3, 'word'), { first: 2, last: 3 });
  // без пробела после «~»: следующее слово начинается по пробелу последнего слога с текстом
  const glued = M.setText(M.setText(us, 3, '~'), 2, 'my '); // In|to␣|my␣|~|eyes␣
  assert.deepEqual(M.shiftRange(glued, 4, 'word'), { first: 4, last: 4 });
  assert.deepEqual(M.shiftRange(glued, 3, 'word'), { first: 2, last: 3 });
});

test('разрезать ноту пополам: вторая половина с «~»; ноту в 1 бит не разрезать', () => {
  const st = M.fromPayload(payload());
  const sec = byText(st, 'Sec').id; // 12..16
  const out = M.splitNote(st, sec);
  assert.deepEqual(M.lines(out)[1].map((x) => [x.start, x.length, x.text]), [[12, 2, 'Sec'], [14, 2, '~'], [16, 2, 'ond']]);
  assert.equal(out.created.length, 1);
  const lo = byText(st, 'lo').id; // 3 бита → 2 + 1
  assert.deepEqual(M.lines(M.splitNote(st, lo))[0].map((x) => x.length), [2, 2, 1, 2]);
  const one = M.resize(st, lo, 'right', -5);
  assert.throws(() => M.splitNote(one, lo), /1 бит/);
});

test('слить со следующей: длина до конца следующей, текст склеен, «~» не дописывается, не через строку', () => {
  const st = M.fromPayload(payload());
  const hel = byText(st, 'Hel').id;
  const out = M.joinNext(st, hel);
  assert.deepEqual(M.lines(out)[0].map((x) => [x.start, x.length, x.text]), [[0, 5, 'Hello'], [6, 2, ' world']]);
  const tilde = M.joinNext(M.setText(st, 1, '~'), hel);
  assert.equal(byText(tilde, 'Hel').length, 5);
  assert.throws(() => M.joinNext(st, byText(st, ' world').id), /друг(ой|ую) строк/);
  assert.throws(() => M.joinNext(st, byText(st, 'Last').id), /друг(ой|ую) строк|последн/i);
});

test('новая строка с ноты и склейка строк; бит разрыва пересчитывается', () => {
  const st = M.fromPayload(payload());
  const out = M.startLine(st, byText(st, ' world').id);
  assert.deepEqual(texts(out), [['Hel', 'lo'], [' world'], ['Sec', 'ond'], ['Last']]);
  assert.deepEqual(M.toPayload(out).lines.map((l) => l.break_beat), [5, 10, 22, null]);
  assert.throws(() => M.startLine(st, byText(st, 'Sec').id), /уже начинает строку/);
  const merged = M.mergeLineAt(st, byText(st, 'Sec').id);
  assert.deepEqual(texts(merged), [['Hel', 'lo', ' world', 'Sec', 'ond'], ['Last']]);
  assert.deepEqual(M.toPayload(merged).lines.map((l) => l.break_beat), [22, null]);
  assert.throws(() => M.mergeLineAt(st, byText(st, 'Hel').id), /перв/);
});

test('золотые: «:» ↔ «*» для выбранных', () => {
  const st = M.fromPayload(payload());
  const ids = [byText(st, 'Hel').id, byText(st, 'Last').id]; // ':' и '*'
  const gold = M.toggleGold(st, ids);
  assert.deepEqual(ids.map((id) => gold.notes.find((x) => x.id === id).type), ['*', '*']);
  const plain = M.toggleGold(gold, ids);
  assert.deepEqual(ids.map((id) => plain.notes.find((x) => x.id === id).type), [':', ':']);
});

test('отстукивание: нота встаёт на новое время и длину, текст и высота сохраняются', () => {
  const st = M.fromPayload(payload());
  const lo = byText(st, 'lo').id;
  const out = M.retime(st, lo, 7, 0);
  const x = byText(out, 'lo');
  assert.deepEqual([x.start, x.length, x.pitch, x.text], [7, 1, 5, 'lo']);
  assert.deepEqual(texts(out)[0], ['Hel', ' world', 'lo']);
  // до начала трека: gap уменьшается, остальные ноты звучат там же
  const early = M.retime(st, byText(st, 'Hel').id, -2, 2);
  assert.equal(early.gap, 900);
  assert.deepEqual(early.notes.map((n) => n.start), [0, 4, 8, 14, 18, 26]);
});

test('проверка перед сохранением — как на сервере (§14): перекрытие с номером строки и слогом', () => {
  const st = M.fromPayload(payload());
  assert.equal(M.validate(st), null);
  assert.equal(M.overlaps(st).size, 0);
  // «Sec» (12..16) растянута до 18: перекрывает «ond» (16) — строка 2
  const over = M.resize(st, byText(st, 'Sec').id, 'right', 2);
  assert.deepEqual([...M.overlaps(over)].sort(), [byText(st, 'Sec').id, byText(st, 'ond').id].sort());
  assert.deepEqual(M.validate(over), { message: 'Ноты перекрываются: строка 2, слог «ond»', id: byText(st, 'ond').id });
  // вплотную — не перекрытие
  assert.equal(M.validate(M.resize(st, byText(st, 'lo').id, 'right', 1)), null);
  // пустой слог допустим (§15)
  assert.equal(M.validate(M.setText(st, 0, '')), null);
  const bad = (patch) => ({ ...st, notes: st.notes.map((x, i) => (i === 3 ? { ...x, ...patch } : x)) });
  assert.match(M.validate(bad({ type: 'X' })).message, /тип/i);
  assert.match(M.validate(bad({ pitch: 101 })).message, /Высота ноты — от −40 до 100/);
  assert.match(M.validate(bad({ length: 0 })).message, /1 бит/);
  assert.match(M.validate(bad({ text: 'a\nb' })).message, /перевод/i);
  assert.equal(M.validate(bad({ type: 'X' })).id, 3);
  assert.match(M.validate({ ...st, gap: -1 }).message, /Раньше начала трека/);
});

test('история: отмена/повтор, новая правка обрезает повтор, не больше 200 шагов', () => {
  const h = M.history();
  const s0 = M.fromPayload(payload());
  assert.equal(h.canUndo(), false);
  const s1 = M.setText(s0, 0, 'A'); h.push(s0);
  const s2 = M.setText(s1, 0, 'B'); h.push(s1);
  assert.equal(h.undo(s2), s1);
  assert.equal(h.undo(s1), s0);
  assert.equal(h.canUndo(), false);
  assert.equal(h.undo(s0), null);
  assert.equal(h.redo(s0), s1);
  assert.equal(h.canRedo(), true);
  const s3 = M.setText(s1, 0, 'C'); h.push(s1);
  assert.equal(h.canRedo(), false, 'новая правка после отмены обрезает повтор');
  assert.equal(h.redo(s3), null);
  const big = M.history();
  for (let i = 0; i < 250; i += 1) big.push({ n: i });
  let undone = 0;
  for (let cur = {}; (cur = big.undo(cur)); ) undone += 1;
  assert.equal(undone, 200);
});

test('несохранённые правки', () => {
  const st = M.fromPayload(payload());
  assert.equal(M.isDirty(st, st), false);
  assert.equal(M.isDirty(M.setText(st, 0, 'X'), st), true);
  assert.equal(M.isDirty(M.setText(M.setText(st, 0, 'X'), 0, 'Hel'), st), false);
  assert.equal(M.isDirty(M.move(st, [0], 0, 1), st), true);
});

test('время бита и обратно: GAP_ms + beat*60000/(BPM*4)', () => {
  assert.equal(M.beatToMs(100, 1000, 300), 6000);
  assert.equal(M.msToBeat(6000, 1000, 300), 100);
  assert.equal(M.beatToMs(0, null, 300), 0);
});

test('тексты ошибок validate — дословно как 400 сервера', () => {
  const st = M.fromPayload(payload());
  const bad = (patch) => M.validate({ ...st, notes: st.notes.map((x, i) => (i === 3 ? { ...x, ...patch } : x)) }).message;
  assert.equal(bad({ type: 'X' }), 'Неизвестный тип ноты «X»: строка 2, слог «Sec»');
  assert.equal(bad({ start: -1 }), 'Начало ноты раньше бита 0: строка 2, слог «Sec»');
  assert.equal(bad({ length: 0 }), 'Длина ноты — не меньше 1 бита: строка 2, слог «Sec»');
  assert.equal(bad({ pitch: -41 }), 'Высота ноты — от −40 до 100: строка 2, слог «Sec»');
  assert.equal(bad({ text: 'a\nb' }), 'В слоге не может быть перевода строки: строка 2');
  assert.equal(M.validate({ ...st, gap: -1 }).message, 'Раньше начала трека сдвигать некуда: #GAP не может быть меньше 0');
  assert.equal(M.validate({ ...st, notes: [] }).message, 'В песне должна остаться хотя бы одна нота');
  assert.equal(M.PITCH_ERROR, 'Высота ноты — от −40 до 100');
  assert.throws(() => M.move(st, [0], -30, 0), { message: 'Раньше начала трека сдвигать некуда: #GAP не может быть меньше 0' });
});

test('золотые не трогают freestyle/rap (F, R, G)', () => {
  const st = M.fromPayload(payload());
  const fr = { ...st, notes: st.notes.map((x, i) => (i === 1 ? { ...x, type: 'F' } : i === 2 ? { ...x, type: 'R' } : x)) };
  const out = M.toggleGold(fr, [0, 1, 2]);
  assert.deepEqual(out.notes.slice(0, 3).map((x) => x.type), ['*', 'F', 'R']);
  assert.deepEqual(M.toggleGold(out, [0, 1, 2]).notes.slice(0, 3).map((x) => x.type), [':', 'F', 'R']);
});

test('неизвестный id — ошибка «Нет такой ноты»', () => {
  const st = M.fromPayload(payload());
  const ops = [
    () => M.shiftText(st, 99, 1), () => M.mergeLineAt(st, 99), () => M.move(st, [99], 1, 0),
    () => M.resize(st, 99, 'right', 1), () => M.deleteNotes(st, [99]), () => M.setText(st, 99, 'x'),
    () => M.splitNote(st, 99), () => M.joinNext(st, 99), () => M.startLine(st, 99),
    () => M.toggleGold(st, [99]), () => M.retime(st, 99, 1, 1),
  ];
  for (const op of ops) assert.throws(op, { message: 'Нет такой ноты' });
});

test('удалена нота-начало строки: прежний бит разрыва сохраняется в теле PUT', () => {
  const st = M.fromPayload(payload());
  const out = M.deleteNotes(st, [byText(st, 'Sec').id]);
  assert.deepEqual(M.toPayload(out).lines.map((l) => l.break_beat), [10, 22, null]);
});

// Строка в стиле UltraSinger: пробел — в конце слога, «~» тоже бывает с пробелом («~ »).
function usPayload() {
  nid = 0;
  return {
    editable: true, bpm: 300, gap: 0, headers: [],
    lines: [
      { break_beat: null, notes: [n(0, 2, 'In'), n(2, 2, 'to '), n(4, 2, 'my'), n(6, 2, '~ '), n(8, 2, 'eyes ')] },
    ],
  };
}

test('UltraSinger: «~» с пробелами — свободная нота, текст строки сохраняет пробелы между словами', () => {
  const st = M.fromPayload(usPayload());
  assert.equal(M.isFree('~ '), true);
  assert.equal(M.isFree(' ~'), true);
  assert.equal(M.lineText(M.lines(st)[0]), 'Into my eyes');
  // «~» внутри слога (склейка UltraSinger «~w ») в тексте панели не показывается
  assert.equal(M.lineText([{ text: 'Ho' }, { text: '~w ' }, { text: 'can ' }, { text: 'you' }]), 'How can you');
  // сдвиг текста узнаёт «~ » справа свободной
  const my = byText(st, 'my').id;
  assert.deepEqual(texts(M.shiftText(M.setText(st, 4, '~ '), my, 1))[0], ['In', 'to ', '~', 'my', '~ ']);
});

test('слить с «~»-нотой: «~» отбрасывается с любой стороны, пробелы-границы слов остаются', () => {
  const st = M.fromPayload(usPayload());
  const my = byText(st, 'my').id;
  assert.equal(M.joinNext(st, my).notes.find((x) => x.id === my).text, 'my ');
  const tl = byText(st, '~ ').id;
  const out = M.joinNext(st, tl);
  assert.equal(out.notes.find((x) => x.id === tl).text, ' eyes ');
  assert.equal(M.lineText(M.lines(out)[0]), 'Into my eyes');
});

// ---------- дуэты (истории 4, 6–11) ----------

// Дуэт: P1 [A1 a1] [Bo th] [C1], P2 [X2 x2] [Bo th] [Z2]; строка «Bo th» в обеих партиях одинакова → «оба».
// Номера нот в файле: P1 0…4, P2 5…9. Разрыв перед копией «оба» у P2 — свой (6), после неё — 13.
function duetPayload() {
  nid = 0;
  return {
    editable: true, bpm: 300, gap: 1000, headers: [['TITLE', 'T']], duet: true, singers: { p1: 'Аня', p2: 'Боря' },
    lines: [
      { break_beat: 6, player: 1, notes: [n(0, 2, 'A1'), n(2, 2, 'a1')] },
      { break_beat: 14, player: 1, notes: [n(8, 2, 'Bo'), n(10, 2, 'th')] },
      { break_beat: null, player: 1, notes: [n(16, 2, 'C1')] },
      { break_beat: 6, player: 2, notes: [n(0, 3, 'X2'), n(4, 2, 'x2')] },
      { break_beat: 13, player: 2, notes: [n(8, 2, 'Bo'), n(10, 2, 'th')] },
      { break_beat: null, player: 2, notes: [n(20, 2, 'Z2')] },
    ],
  };
}
const duetBody = (data) => ({ gap: data.gap, singers: data.singers, lines: data.lines });
const voiceTexts = (st, v) => M.toPayload(st).lines.filter((l) => l.player === v).map((l) => l.notes.map((x) => x.text));
const voiceIds = (st, v) => M.toPayload(st).lines.filter((l) => l.player === v).map((l) => l.notes.map((x) => x.id));

test('дуэт: обе партии в одном списке, одинаковые строки P1/P2 — одна строка «оба» с двумя источниками', () => {
  const st = M.fromPayload(duetPayload());
  assert.equal(st.duet, true);
  assert.deepEqual(st.singers, { p1: 'Аня', p2: 'Боря' });
  assert.equal(st.notes.length, 8);
  const v = Object.fromEntries(st.notes.map((x) => [x.text, x.voice]));
  assert.deepEqual(v, { A1: 1, a1: 1, Bo: 'both', th: 'both', C1: 1, X2: 2, x2: 2, Z2: 2 });
  assert.deepEqual([byText(st, 'Bo').src, byText(st, 'Bo').src2, byText(st, 'th').src, byText(st, 'th').src2], [2, 7, 3, 8]);
  assert.equal(byText(st, 'X2').src, 5);
  assert.equal(M.fromPayload(payload()).duet, false, 'соло — не дуэт');
});

test('дуэт: выгрузка без правок — блок певца 1, затем певца 2 (с копией «оба»), разрывы и имена как были', () => {
  const data = duetPayload();
  assert.deepEqual(M.toPayload(M.fromPayload(data)), duetBody(duetPayload()));
  assert.equal(M.isDirty(M.fromPayload(data), M.fromPayload(duetPayload())), false);
});

test('дуэт: перекрытия считаются внутри партии — P2 с бита 0 не мешает P1, «оба» проверяется с обеими', () => {
  const st = M.fromPayload(duetPayload());
  assert.deepEqual([...M.overlaps(st)], []);
  assert.equal(M.validate(st), null);
  // Z2 (20) → 11: заезжает на «th» (10..12) копии «оба» во второй партии
  const bad = M.move(st, [byText(st, 'Z2').id], -9, 0);
  assert.deepEqual(new Set(M.overlaps(bad)), new Set([byText(st, 'th').id, byText(st, 'Z2').id]));
  assert.deepEqual(M.validate(bad), { message: 'Певец 2, строка 3: ноты перекрываются, слог «Z2»', id: byText(st, 'Z2').id });
  assert.deepEqual(voiceTexts(bad, 1), [['A1', 'a1'], ['Bo', 'th'], ['C1']], 'первая партия не тронута');
});

test('дуэт: перестановка по времени — внутри партии, сдвиг левее 0 — всей песни через gap', () => {
  const st = M.fromPayload(duetPayload());
  // C1 (16) → 0: обгоняет всю первую партию, вторая не меняется
  const out = M.move(st, [byText(st, 'C1').id], -16, 0);
  assert.deepEqual(voiceTexts(out, 1), [['A1'], ['C1', 'a1'], ['Bo', 'th']]); // флаг строки едет с C1
  assert.deepEqual(voiceIds(out, 2), voiceIds(st, 2));
  // X2 на 2 бита левее 0: вся песня вправо, gap 1000 − 2 × 50
  const left = M.move(st, [byText(st, 'X2').id], -2, 0);
  assert.equal(left.gap, 900);
  assert.equal(byText(left, 'A1').start, 2);
  assert.equal(byText(left, 'X2').start, 0);
  // отстукивание Z2 на бит 1 ставит его первым во второй партии
  assert.deepEqual(voiceTexts(M.retime(st, byText(st, 'Z2').id, 1, 1), 2).slice(0, 2), [['X2'], ['Z2', 'x2']]);
});

test('дуэт: слить, разрезать, ↵ строка, склеить строки — соседи из своей партии', () => {
  const st = M.fromPayload(duetPayload());
  const j = M.joinNext(st, byText(st, 'X2').id); // в общем списке между X2 и x2 стоят ноты певца 1
  assert.deepEqual(voiceTexts(j, 2)[0], ['X2x2']);
  assert.equal(byText(j, 'X2x2').length, 6);
  assert.deepEqual(voiceTexts(j, 1), voiceTexts(st, 1));
  assert.throws(() => M.joinNext(st, byText(st, 'x2').id), /в другой строке/);
  const sp = M.splitNote(st, byText(st, 'Bo').id); // «оба» режется в обеих партиях
  assert.deepEqual(voiceTexts(sp, 1)[1], ['Bo', '~', 'th']);
  assert.deepEqual(voiceIds(sp, 2)[1], [7, null, 8]);
  assert.deepEqual(voiceTexts(M.startLine(st, byText(st, 'x2').id), 2), [['X2'], ['x2'], ['Bo', 'th'], ['Z2']]);
  assert.throws(() => M.mergeLineAt(st, byText(st, 'X2').id), /первая строка/);
  assert.throws(() => M.mergeLineAt(st, byText(st, 'Z2').id), /разных певцов/);
  const m = M.mergeLineAt(M.startLine(st, byText(st, 'x2').id), byText(st, 'x2').id);
  assert.deepEqual(voiceTexts(m, 2), voiceTexts(st, 2));
});

test('дуэт: ↵ у строки «оба» склеивает в партии полосы — и только если строки соседние в обеих партиях', () => {
  const st = M.fromPayload(duetPayload());
  // C1 → «оба»: строки «Bo th» и «C1» соседние и у певца 1, и у певца 2 — склейка с нижней полосы (P2)
  const both = M.setVoice(st, [byText(st, 'C1').id], 'both');
  const m = M.mergeLineAt(both, byText(both, 'C1').id, 2);
  assert.deepEqual(voiceTexts(m, 2), [['X2', 'x2'], ['Bo', 'th', 'C1'], ['Z2']]);
  assert.deepEqual(voiceTexts(m, 1), [['A1', 'a1'], ['Bo', 'th', 'C1']]);
  // C1 → певцу 2, Z2 → «оба»: у певца 1 «Bo th» и «Z2» рядом, у певца 2 между ними строка «C1»
  const mid = M.setVoice(M.setVoice(st, [byText(st, 'C1').id], 2), [byText(st, 'Z2').id], 'both');
  assert.deepEqual(voiceTexts(mid, 2), [['X2', 'x2'], ['Bo', 'th'], ['C1'], ['Z2']]);
  assert.throws(() => M.mergeLineAt(mid, byText(mid, 'Z2').id, 2), /разных певцов/);
  assert.throws(() => M.mergeLineAt(mid, byText(mid, 'Z2').id, 1), /у певца 2 между ними своя строка/);
});

test('дуэт: удаление и добавление нот — в партии ноты; вторую партию можно опустошить', () => {
  const st = M.fromPayload(duetPayload());
  assert.deepEqual(voiceTexts(M.deleteNotes(st, [byText(st, 'X2').id]), 2), [['x2'], ['Bo', 'th'], ['Z2']]);
  const no2 = M.deleteNotes(st, ['X2', 'x2', 'Z2'].map((t) => byText(st, t).id));
  assert.deepEqual(voiceTexts(no2, 2), [['Bo', 'th']]);
  assert.throws(() => M.deleteNotes(st, st.notes.map((x) => x.id)), /хотя бы одна нота/);
  const add = M.addNote(st, { start: 24, pitch: 3, voice: 2 });
  assert.deepEqual(voiceTexts(add, 2).at(-1), ['Z2', '']);
  assert.deepEqual(voiceTexts(add, 1), voiceTexts(st, 1));
  const li = M.lines(st).findIndex((l) => l[0].text === 'X2');
  const more = M.addNotesToLine(st, li, 1);
  assert.deepEqual(voiceTexts(more, 2)[0], ['X2', 'x2', '']);
  assert.equal(more.notes.find((x) => x.id === more.created[0]).voice, 2);
});

test('дуэт: сдвиг текста «до конца песни» — до конца партии ноты', () => {
  const st = M.fromPayload(duetPayload());
  const out = M.shiftTextBy(st, byText(st, 'X2').id, 1, 'song');
  assert.deepEqual(voiceTexts(out, 2), [['~', 'X2'], ['x2', 'Bo'], ['thZ2']]);
  assert.deepEqual(voiceTexts(out, 1), [['A1', 'a1'], ['x2', 'Bo'], ['C1']], 'ноты «оба» общие, певец 1 не тронут');
  assert.throws(() => M.shiftTextBy(st, byText(st, 'Z2').id, 1, 'song'), /Правее нот нет/);
});

test('setVoice: строки выбранных нот целиком переходят к певцу 1, 2 или «оба»', () => {
  const st = M.fromPayload(duetPayload());
  const a = M.setVoice(st, [byText(st, 'a1').id], 2); // строка [A1 a1] целиком
  assert.deepEqual(voiceTexts(a, 1), [['Bo', 'th'], ['C1']]);
  assert.deepEqual(voiceTexts(a, 2), [['X2', 'x2'], ['A1', 'a1'], ['Bo', 'th'], ['Z2']]); // строка целиком, при равном начале — после
  assert.equal(byText(a, 'A1').voice, 2);
  // певец 2 → «оба»: строка появляется в P1 новой (id null), копия P2 — прежние номера
  const b = M.setVoice(st, [byText(st, 'X2').id], 'both');
  assert.deepEqual(voiceIds(b, 1), [[0, 1], [null, null], [2, 3], [4]]);
  assert.deepEqual(voiceIds(b, 2)[0], [5, 6]);
  // «оба» → певец 2: остаётся копия P2; → певец 1: копия P1
  assert.deepEqual(voiceIds(M.setVoice(st, [byText(st, 'Bo').id], 2), 2)[1], [7, 8]);
  assert.deepEqual(voiceIds(M.setVoice(st, [byText(st, 'Bo').id], 2), 1), [[0, 1], [4]]);
  assert.deepEqual(voiceIds(M.setVoice(st, [byText(st, 'th').id], 1), 2), [[5, 6], [9]]);
  assert.equal(M.setVoice(st, [byText(st, 'A1').id], 1), st, 'певец тот же — состояние то же');
  assert.throws(() => M.setVoice(st, [byText(st, 'A1').id], 3), /1, 2 или «оба»/);
  assert.throws(() => M.setVoice(M.fromPayload(payload()), [0], 2), /не дуэт/);
});

test('makeDuet / makeSolo: соло → дуэт (всё певцу 1), дуэт → соло (копии «оба» схлопываются)', () => {
  const solo = M.fromPayload(payload());
  const d = M.makeDuet(solo);
  assert.equal(d.duet, true);
  assert.ok(d.notes.every((x) => x.voice === 1));
  assert.deepEqual(M.toPayload(d).lines.map((l) => l.player), [1, 1, 1]);
  assert.deepEqual(M.toPayload(d).singers, { p1: '', p2: '' });
  assert.equal(M.isDirty(d, solo), true);
  assert.throws(() => M.makeDuet(d), /уже дуэт/);
  const s = M.makeSolo(M.fromPayload(duetPayload()));
  assert.equal(s.duet, false);
  const body = M.toPayload(s);
  assert.equal(body.singers, undefined);
  assert.ok(body.lines.every((l) => l.player === undefined));
  assert.equal(s.notes.length, 8, '«оба» — одна копия');
  assert.deepEqual(body.lines.map((l) => l.notes.map((x) => x.id)), [[0, 1], [5, 6], [2, 3], [4], [9]]);
  assert.throws(() => M.makeSolo(solo), /не дуэт/);
});

test('setSingers: имена в теле PUT, правка имени — несохранённая правка; history хранит снимки', () => {
  const st = M.fromPayload(duetPayload());
  const out = M.setSingers(st, ' Вера ', '');
  assert.deepEqual(M.toPayload(out).singers, { p1: 'Вера', p2: '' });
  assert.equal(M.isDirty(out, st), true);
  assert.equal(M.isDirty(M.setVoice(st, [byText(st, 'Z2').id], 1), st), true);
  assert.throws(() => M.setSingers(st, 'a\nb', ''), /перевода строки/);
  assert.throws(() => M.setSingers(M.fromPayload(payload()), 'a', 'b'), /не дуэт/);
  const h = M.history();
  h.push(st);
  assert.deepEqual(h.undo(out).singers, { p1: 'Аня', p2: 'Боря' });
});

test('voiceNotes / voiceLines: ноты и строки партии вместе с «оба»; validate дуэта называет певца', () => {
  const st = M.fromPayload(duetPayload());
  assert.deepEqual(M.voiceNotes(st, 2).map((x) => x.text), ['X2', 'x2', 'Bo', 'th', 'Z2']);
  assert.deepEqual(M.voiceLines(st, 1).map((l) => l.map((x) => x.text)), [['A1', 'a1'], ['Bo', 'th'], ['C1']]);
  assert.equal(M.lines(st).length, 5, 'строка «оба» — одна');
  const bad = { ...st, notes: st.notes.map((x) => (x.text === 'Z2' ? { ...x, type: 'Q' } : x)) };
  assert.deepEqual(M.validate(bad), { message: 'Певец 2, строка 3: неизвестный тип ноты «Q», слог «Z2»', id: byText(st, 'Z2').id });
});

test('partOf / partNotes / parts: партия ноты — певец 2 во второй, певец 1 и «оба» в первой; у соло — все ноты', () => {
  const st = M.fromPayload(duetPayload());
  assert.deepEqual(['A1', 'Bo', 'X2'].map((t) => M.partOf(byText(st, t))), [1, 1, 2]);
  assert.equal(M.partOf({ id: 0 }), 1, 'нота без певца — певца 1');
  assert.deepEqual(M.partNotes(st, byText(st, 'Z2').id).map((x) => x.text), ['X2', 'x2', 'Bo', 'th', 'Z2']);
  assert.deepEqual(M.partNotes(st, byText(st, 'th').id).map((x) => x.text), ['A1', 'a1', 'Bo', 'th', 'C1']);
  const solo = M.fromPayload(payload());
  assert.equal(M.partNotes(solo, solo.notes[2].id), solo.notes);
  assert.throws(() => M.partNotes(st, 99), /Нет такой ноты/);
  assert.deepEqual([M.parts(st), M.parts(solo)], [[1, 2], [1]]);
});

test('allVoice: все выбранные ноты уже у певца v (пустой выбор — нет)', () => {
  const st = M.fromPayload(duetPayload());
  const ids = (...t) => t.map((x) => byText(st, x).id);
  assert.equal(M.allVoice(st, ids('X2', 'Z2'), 2), true);
  assert.equal(M.allVoice(st, ids('X2', 'Bo'), 2), false, '«оба» — не певец 2');
  assert.equal(M.allVoice(st, ids('Bo', 'th'), 'both'), true);
  assert.equal(M.allVoice(st, [], 1), false);
  assert.equal(M.allVoice(st, [99], 1), false);
});

test('VOICE_LABELS: подписи певцов строки — кнопка, «кому», «у кого»', () => {
  assert.deepEqual(M.VOICES.map((v) => M.VOICE_LABELS[v].short), ['1', '2', 'оба']);
  assert.deepEqual(M.VOICES.map((v) => M.VOICE_LABELS[v].to), ['певцу 1', 'певцу 2', 'обоим']);
  assert.deepEqual(M.VOICES.map((v) => M.VOICE_LABELS[v].at), ['певца 1', 'певца 2', 'обоих']);
  assert.deepEqual(M.VOICES.map((v) => M.VOICE_LABELS[v].who), ['певец 1', 'певец 2', 'оба']);
});

test('дуэт: нота певца 1 перекрывает ноту «оба» → ошибка у певца 1', () => {
  const st = M.fromPayload(duetPayload());
  // a1 (2..4) тянется до 9: заезжает на «Bo» (8..10) строки «оба»
  const bad = M.resize(st, byText(st, 'a1').id, 'right', 5);
  assert.ok(M.overlaps(bad).has(byText(st, 'Bo').id));
  assert.deepEqual(M.validate(bad), { message: 'Певец 1, строка 2: ноты перекрываются, слог «Bo»', id: byText(st, 'Bo').id });
});

test('дуэт: разрыв после последней строки певца 1 («- N» перед P2) доезжает до PUT как был', () => {
  const data = (brk) => ({
    editable: true, bpm: 300, gap: 0, headers: [], duet: true, singers: { p1: '', p2: '' },
    lines: [
      { break_beat: brk, player: 1, notes: [{ id: 0, type: ':', start: 0, length: 4, pitch: 5, text: 'Раз' }] },
      { break_beat: null, player: 2, notes: [{ id: 1, type: ':', start: 8, length: 4, pitch: 5, text: 'Два' }] },
    ],
  });
  assert.equal(M.toPayload(M.fromPayload(data(6))).lines[0].break_beat, 6);
  assert.equal(M.toPayload(M.fromPayload(data(null))).lines[0].break_beat, null);
  assert.equal(M.isDirty(M.fromPayload(data(6)), M.fromPayload(data(6))), false);
});

// ---------- «Строки как в тексте» (POST /api/songs/{id}/notes/lines) ----------

test('lineStartsRequest: тексты нот соло по порядку и индексы начал строк', () => {
  const st = M.fromPayload(payload());
  assert.deepEqual(M.lineStartsRequest(st), { texts: ['Hel', 'lo', ' world', 'Sec', 'ond', 'Last'], starts: [0, 3, 5] });
  const out = M.startLine(st, byText(st, ' world').id);
  assert.deepEqual(M.lineStartsRequest(out).starts, [0, 2, 3, 5]);
  assert.throws(() => M.lineStartsRequest(M.fromPayload(duetPayload())), /дуэт/);
});

test('setLineStarts: строки с указанных нот, новые разрывы — конец предыдущей ноты, прежние — сохраняются', () => {
  const st = M.fromPayload(payload());
  const out = M.setLineStarts(st, [0, 2, 5]);
  assert.deepEqual(texts(out), [['Hel', 'lo'], [' world', 'Sec', 'ond'], ['Last']]);
  assert.deepEqual(M.toPayload(out).lines.map((l) => l.break_beat), [5, 22, null]);
  assert.deepEqual(texts(st), [['Hel', 'lo', ' world'], ['Sec', 'ond'], ['Last']], 'исходное состояние не меняется');
  assert.deepEqual(out.created, []);
  // первая нота — всегда начало строки, даже без 0 в списке
  assert.deepEqual(texts(M.setLineStarts(st, [3])), [['Hel', 'lo', ' world'], ['Sec', 'ond', 'Last']]);
  assert.deepEqual(texts(M.setLineStarts(st, [])), [['Hel', 'lo', ' world', 'Sec', 'ond', 'Last']]);
  // ничего не меняется — то же состояние (правкой не считается)
  assert.equal(M.setLineStarts(st, [0, 3, 5]), st);
  // после отмены разрыва и возврата границы бит разрыва пересчитан, а не взят из чужой строки
  const back = M.setLineStarts(M.setLineStarts(st, [0, 2, 5]), [0, 3, 5]);
  assert.deepEqual(M.toPayload(back).lines.map((l) => l.break_beat), [8, 22, null]);
});

test('setLineStarts: неверные индексы и дуэт — ошибка', () => {
  const st = M.fromPayload(payload());
  for (const bad of [[6], [-1], [1.5], ['2'], [3, 2], [2, 2], null]) {
    assert.throws(() => M.setLineStarts(st, bad), /Неверн/, JSON.stringify(bad));
  }
  assert.throws(() => M.setLineStarts(M.fromPayload(duetPayload()), [0]), /дуэт/);
});

// ---------- перетаскивание разрыва строки (истории 1–5, §14) ----------

test('разрыв: тяга поверх нот переносит их в соседнюю строку, в паузе — только бит разрыва', () => {
  const st = M.fromPayload(payload());
  const sec = byText(st, 'Sec').id;
  // влево поверх « world» (6): нота уходит в следующую строку; бит 6 — в паузе 5..6
  const left = M.moveBreak(st, sec, 6);
  assert.deepEqual(texts(left), [['Hel', 'lo'], [' world', 'Sec', 'ond'], ['Last']]);
  assert.deepEqual(M.toPayload(left).lines.map((l) => l.break_beat), [6, 22, null]);
  // вправо поверх «Sec» (12..16) до бита 15: первая нота с start ≥ 15 — «ond», разрыв — конец «Sec»
  const right = M.moveBreak(st, sec, 15);
  assert.deepEqual(texts(right), [['Hel', 'lo', ' world', 'Sec'], ['ond'], ['Last']]);
  assert.deepEqual(M.toPayload(right).lines.map((l) => l.break_beat), [16, 22, null]);
  // в паузе 8..12: ноты на месте, разрыв — точка отпускания (с округлением до бита)
  const pause = M.moveBreak(st, sec, 9.4);
  assert.deepEqual(texts(pause), texts(st));
  assert.deepEqual(M.toPayload(pause).lines.map((l) => l.break_beat), [9, 22, null]);
  // правый разрыв строки «Sec ond» влево — её конец укорачивается
  const end = M.moveBreak(st, byText(st, 'Last').id, 14);
  assert.deepEqual(texts(end), [['Hel', 'lo', ' world'], ['Sec'], ['ond', 'Last']]);
  assert.deepEqual(texts(st), [['Hel', 'lo', ' world'], ['Sec', 'ond'], ['Last']], 'исходное состояние не меняется');
});

test('разрыв: не перепрыгивает соседний — в каждой строке остаётся нота; первая строка и не начало — ошибка', () => {
  const st = M.fromPayload(payload());
  const sec = byText(st, 'Sec').id;
  const far = M.moveBreak(st, sec, 30);
  assert.deepEqual(texts(far), [['Hel', 'lo', ' world', 'Sec'], ['ond'], ['Last']]);
  const back = M.moveBreak(st, sec, -5);
  assert.deepEqual(texts(back), [['Hel'], ['lo', ' world', 'Sec', 'ond'], ['Last']]);
  assert.deepEqual(M.toPayload(back).lines.map((l) => l.break_beat), [2, 22, null]);
  assert.throws(() => M.moveBreak(st, byText(st, 'Hel').id, 3), /перв/);
  assert.throws(() => M.moveBreak(st, byText(st, 'lo').id, 3), /не начинает строку/);
  assert.throws(() => M.moveBreak(st, 99, 3), /Нет такой ноты/);
  assert.equal(M.moveBreak(st, sec, 10), st, 'без изменений — то же состояние (шага отмены нет)');
});

test('разрыв дуэта: двигает только свою партию; «оба» — лишь при одинаковой границе у обоих певцов', () => {
  const st = M.fromPayload(duetPayload());
  // своя партия: у певца 2 «X2 | x2» — разрыв в паузе 3..4, у певца 1 ничего не меняется
  const s2 = M.startLine(st, byText(st, 'x2').id);
  const own = M.moveBreak(s2, byText(s2, 'x2').id, 3, 2);
  assert.deepEqual(voiceTexts(own, 2), [['X2'], ['x2'], ['Bo', 'th'], ['Z2']]);
  assert.equal(M.toPayload(own).lines.find((l) => l.player === 2).break_beat, 3);
  assert.deepEqual(voiceIds(own, 1), voiceIds(st, 1));
  // пауза перед «Z2» у певца 2: бит 15, разрыв певца 1 после «Bo th» (14) прежний
  const z = M.moveBreak(st, byText(st, 'Z2').id, 15, 2);
  assert.deepEqual(M.toPayload(z).lines.map((l) => l.break_beat), [6, 14, null, 6, 15, null]);
  // «th» («оба») и «Z2» (певца 2) в одну строку не сходятся
  assert.throws(() => M.moveBreak(st, byText(st, 'Z2').id, 9, 2), /разных певцов/);
  // C1 → певцу 2, Z2 → «оба»: у певца 1 «Bo th | Z2» рядом, у певца 2 между ними «C1» — граница разная
  const mid = M.setVoice(M.setVoice(st, [byText(st, 'C1').id], 2), [byText(st, 'Z2').id], 'both');
  assert.throws(() => M.moveBreak(mid, byText(mid, 'Z2').id, 9, 1), /«оба»/);
  // «Bo» («оба») в строку певца 2 «X2 x2» — строки разных певцов
  assert.throws(() => M.moveBreak(st, byText(st, 'Bo').id, 10, 2), /разных певцов/);
  // «Bo th» и «C1» — «оба» и соседние у обоих: граница переходит у обоих одинаково
  const both = M.setVoice(st, [byText(st, 'C1').id], 'both');
  const m = M.moveBreak(both, byText(both, 'C1').id, 10, 2);
  assert.deepEqual(voiceTexts(m, 1), [['A1', 'a1'], ['Bo'], ['th', 'C1']]);
  assert.deepEqual(voiceTexts(m, 2), [['X2', 'x2'], ['Bo'], ['th', 'C1'], ['Z2']]);
  assert.deepEqual(M.toPayload(m).lines.map((l) => l.break_beat), [6, 10, null, 6, 10, 18, null]);
});
