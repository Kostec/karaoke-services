// Точка входа для `node --test tests/frontend/`: Node 22+ не обходит каталог сам,
// а загружает его как модуль — здесь подключаются все *.test.mjs рядом.
import { readdirSync } from 'node:fs';

const here = new URL('./', import.meta.url);
for (const name of readdirSync(here).filter((f) => f.endsWith('.test.mjs')).sort()) {
  await import(new URL(name, here));
}
