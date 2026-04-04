import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(process.cwd(), 'output', 'takeoff-audit');

function ensureDir() {
  fs.mkdirSync(ROOT, { recursive: true });
}

function appendJsonl(fileName, row) {
  ensureDir();
  const target = path.join(ROOT, fileName);
  fs.appendFileSync(target, `${JSON.stringify(row)}\n`, 'utf8');
}

export function logDecision(event, payload) {
  appendJsonl('decision-log.jsonl', {
    at: new Date().toISOString(),
    event,
    ...payload,
  });
}

export function enqueueReview(payload) {
  appendJsonl('review-queue.jsonl', {
    at: new Date().toISOString(),
    ...payload,
  });
}
