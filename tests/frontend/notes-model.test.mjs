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
