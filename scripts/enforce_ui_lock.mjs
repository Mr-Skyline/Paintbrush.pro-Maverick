#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

const ROOT = process.cwd();
const LOCK_PATH = path.join(ROOT, 'scripts', 'ui_lock.json');

if (process.env.UI_LOCK_BYPASS === '1') {
  console.log('ui-lock: bypassed via UI_LOCK_BYPASS=1');
  process.exit(0);
}

if (!existsSync(LOCK_PATH)) {
  console.error(`ui-lock: missing lock file at ${LOCK_PATH}`);
  console.error('ui-lock: generate it with "node scripts/generate_ui_lock.mjs".');
  process.exit(2);
}

const lock = JSON.parse(readFileSync(LOCK_PATH, 'utf-8'));
const hashMap =
  lock.files && typeof lock.files === 'object' && !Array.isArray(lock.files)
    ? lock.files
    : {};
const files = Object.keys(hashMap);

function sha256ForFile(absPath) {
  const content = readFileSync(absPath);
  return createHash('sha256').update(content).digest('hex');
}

const missing = [];
const changed = [];

for (const rel of files) {
  const abs = path.join(ROOT, rel);
  if (!existsSync(abs)) {
    missing.push(rel);
    continue;
  }
  const actual = sha256ForFile(abs);
  const expected = hashMap[rel];
  if (typeof expected !== 'string' || expected !== actual) {
    changed.push({ rel, expected, actual });
  }
}

if (missing.length === 0 && changed.length === 0) {
  console.log(`ui-lock: ok (${files.length} tracked UI files)`);
  process.exit(0);
}

console.error('ui-lock: blocked UI change detected.');
if (missing.length) {
  console.error('ui-lock: missing files:');
  for (const rel of missing) console.error(`  - ${rel}`);
}
if (changed.length) {
  console.error('ui-lock: changed files:');
  for (const row of changed) console.error(`  - ${row.rel}`);
}
console.error('');
console.error('To intentionally update UI lock baseline:');
console.error('  node scripts/generate_ui_lock.mjs');
console.error('Then commit scripts/ui_lock.json with approved UI changes.');
console.error('');
console.error('For temporary local bypass only:');
console.error('  UI_LOCK_BYPASS=1 npm run build');

process.exit(1);
