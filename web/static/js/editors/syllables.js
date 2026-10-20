// Деление строки текста на слоги для редактора нот (спека §6). Чистый модуль без DOM.
//
// Слог на каждую гласную (рус. «аеёиоуыэюя», лат. «aeiouy»); из согласных между гласными
// одна уходит в следующий слог, но «й ь ъ» остаются с предыдущим. «|» — принудительная
// граница. Пробел перед словом стоит в начале его первого слога, как в .txt.

const VOWELS = /[аеёиоуыэюяaeiouy]/i;
const LATIN_VOWELS = /[aeiouy]/i;
const STAY = /[йьъ]/i;

/** Слоги одного куска слова (без пробелов и «|»). */
function splitPart(part) {
  const out = [];
  let cur = '';
  let seen = false;
  let prev = '';
  for (const ch of part) {
    const vowel = VOWELS.test(ch);
    // латинские гласные подряд — один слог (you, rain, beau)
    const diphthong = LATIN_VOWELS.test(ch) && LATIN_VOWELS.test(prev);
    prev = ch;
    if (vowel && seen && !diphthong) {
      const chars = [...cur];
      const last = chars[chars.length - 1];
      const give = !VOWELS.test(last) && !STAY.test(last) ? 1 : 0;
      out.push(chars.slice(0, chars.length - give).join(''));
      cur = chars.slice(chars.length - give).join('');
    }
    if (vowel) seen = true;
    cur += ch;
  }
  if (cur) out.push(cur);
  return out;
}

/** Слоги слова: куски между «|» делятся отдельно. */
function splitWord(word) {
  return word.split('|').filter(Boolean).flatMap(splitPart);
}

/**
 * Строка → слоги в формате .txt (пробел — в начале первого слога каждого слова, кроме первого).
 * Слово без гласных («в», «с») приклеивается к следующему слову, в конце строки — к предыдущему.
 */
export function toSyllables(text) {
  const words = String(text).trim().split(/\s+/).filter((w) => w.replace(/\|/g, ''));
  const groups = [];
  let prefix = '';
  for (const word of words) {
    if (!VOWELS.test(word)) {
      prefix += `${word.replace(/\|/g, '')} `;
      continue;
    }
    const syls = splitWord(word);
    syls[0] = prefix + syls[0];
    prefix = '';
    groups.push(syls);
  }
  if (prefix) {
    if (groups.length) {
      const last = groups[groups.length - 1];
      last[last.length - 1] += ` ${prefix.trim()}`;
    } else {
      groups.push([prefix.trim()]);
    }
  }
  return groups.flatMap((syls, gi) => syls.map((s, k) => (gi > 0 && k === 0 ? ` ${s}` : s)));
}
