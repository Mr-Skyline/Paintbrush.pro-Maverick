#!/usr/bin/env node
/**
 * Optional Node helper for "watch folder" workflows.
 * Browsers cannot watch arbitrary OS paths; run this on the machine that
 * receives PDFs and POST to your app or drop copies into a synced folder.
 *
 * Usage (example):
 *   node scripts/watch-incoming.mjs "C:\\Blueprints\\Incoming"
 *
 * Stub: logs new .pdf files. Extend with chokidar + fetch to your API.
 */
import fs from 'fs';
import path from 'path';

const dir = process.argv[2];
if (!dir) {
  console.error('Usage: node watch-incoming.mjs <folder>');
  process.exit(1);
}

console.log('Watching (polling stub):', path.resolve(dir));
console.log('Add chokidar + integration to auto-create projects / call Boost.');

setInterval(() => {
  try {
    const names = fs.readdirSync(dir).filter((f) => /\.pdf$/i.test(f));
    if (names.length) console.log('[incoming]', names.length, 'PDF(s)');
  } catch {
    /* missing folder */
  }
}, 10_000);
