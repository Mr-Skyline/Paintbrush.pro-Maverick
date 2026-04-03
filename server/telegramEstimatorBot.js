import 'dotenv/config';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { Telegraf } from 'telegraf';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.join(__dirname, '..');

function readTextIfExists(filePath) {
  try {
    if (!fs.existsSync(filePath)) return '';
    return fs.readFileSync(filePath, 'utf8').trim();
  } catch {
    return '';
  }
}

function readEnvValueFromEnvTxt(key) {
  const envTxt = readTextIfExists(path.join(ROOT_DIR, '.env.txt'));
  if (!envTxt) return '';
  const line = envTxt
    .split(/\r?\n/)
    .find((row) => row.trim().startsWith(`${key}=`) && !row.trim().startsWith('#'));
  if (!line) return '';
  return line.slice(line.indexOf('=') + 1).trim();
}

function resolveTelegramToken() {
  if (process.env.TELEGRAM_BOT_TOKEN) return process.env.TELEGRAM_BOT_TOKEN;
  const fromEnvTxt = readEnvValueFromEnvTxt('TELEGRAM_BOT_TOKEN');
  if (fromEnvTxt) return fromEnvTxt;
  const fromTxtFile = readTextIfExists(path.join(ROOT_DIR, 'telegram.txt'));
  return fromTxtFile || '';
}

function resolveGrokKey() {
  if (process.env.GROK_API_KEY) return process.env.GROK_API_KEY;
  if (process.env.XAI_API_KEY) return process.env.XAI_API_KEY;
  const fromEnvTxt = readEnvValueFromEnvTxt('GROK_API_KEY');
  if (fromEnvTxt) return fromEnvTxt;
  const fromXaiEnvTxt = readEnvValueFromEnvTxt('XAI_API_KEY');
  if (fromXaiEnvTxt) return fromXaiEnvTxt;
  const fromTxtFile = readTextIfExists(path.join(ROOT_DIR, 'builderbot grok api.txt'));
  return fromTxtFile || '';
}

const BOT_TOKEN = resolveTelegramToken();
const GROK_API_KEY = resolveGrokKey();
const GROK_MODEL = process.env.GROK_MODEL || 'grok-2-latest';
const PAINT_COVERAGE = Number(process.env.PAINT_COVERAGE_SQFT_PER_GALLON || 350);
const DEFAULT_COATS = Number(process.env.DEFAULT_PAINT_COATS || 2);

if (!BOT_TOKEN) {
  throw new Error('Missing TELEGRAM_BOT_TOKEN (.env, .env.txt, or telegram.txt).');
}

function redactToken(token) {
  if (!token || token.length < 10) return '***';
  return `${token.slice(0, 6)}...${token.slice(-4)}`;
}

function validateTelegramTokenFormat(token) {
  const strictPattern = /^\d{6,}:[A-Za-z0-9_-]{30,}$/;
  if (!strictPattern.test(token)) {
    return {
      ok: false,
      reason:
        'Token format is invalid. Expected "<numeric_bot_id>:<long_secret>" from BotFather.',
    };
  }
  return { ok: true, reason: '' };
}

async function assertTelegramTokenIsOperational(token) {
  const format = validateTelegramTokenFormat(token);
  if (!format.ok) {
    throw new Error(`TELEGRAM_BOT_TOKEN rejected (${redactToken(token)}): ${format.reason}`);
  }

  // Fail fast on stale/revoked or mistyped tokens by verifying directly with Telegram.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(`https://api.telegram.org/bot${token}/getMe`, {
      method: 'GET',
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data?.ok) {
      const upstream = data?.description || `${response.status} ${response.statusText}`;
      throw new Error(`Telegram API rejected token (${redactToken(token)}): ${upstream}`);
    }
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('Telegram token validation timed out. Check internet connection and retry.');
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

const bot = new Telegraf(BOT_TOKEN);
const sessions = new Map();

function nowIso() {
  return new Date().toISOString();
}

function createSession() {
  return {
    startedAt: nowIso(),
    completedAt: null,
    entries: [],
  };
}

function getSession(chatId) {
  if (!sessions.has(chatId)) sessions.set(chatId, createSession());
  return sessions.get(chatId);
}

function parseNumber(input) {
  const n = Number(input);
  return Number.isFinite(n) ? n : null;
}

function extractMeasurement(text) {
  const normalized = text.replace(/,/g, ' ').trim();
  const locationMatch = normalized.match(/^([^:]{2,80}):/);
  const location = locationMatch ? locationMatch[1].trim() : 'Unspecified area';

  const sqftMatch = normalized.match(/(\d+(?:\.\d+)?)\s*(sq\.?\s*ft|sqft|sf|ft2|ft\^2)\b/i);
  const dimMatch = normalized.match(
    /(\d+(?:\.\d+)?)\s*(?:ft|feet|')?\s*(?:x|by)\s*(\d+(?:\.\d+)?)\s*(?:ft|feet|')?/i
  );
  const coatsMatch = normalized.match(/(\d+)\s*coats?\b/i);

  const coats = coatsMatch ? parseNumber(coatsMatch[1]) : DEFAULT_COATS;
  if (!coats) return null;

  if (sqftMatch) {
    const areaSqft = parseNumber(sqftMatch[1]);
    if (!areaSqft) return null;
    return {
      location,
      areaSqft,
      coats,
      source: 'sqft',
    };
  }

  if (dimMatch) {
    const lengthFt = parseNumber(dimMatch[1]);
    const heightFt = parseNumber(dimMatch[2]);
    if (!lengthFt || !heightFt) return null;
    return {
      location,
      lengthFt,
      heightFt,
      areaSqft: Number((lengthFt * heightFt).toFixed(2)),
      coats,
      source: 'dimensions',
    };
  }

  return null;
}

function summarizeSession(session) {
  const measurements = session.entries.filter((e) => e.type === 'measurement');
  const notes = session.entries.filter((e) => e.type === 'note');
  const photos = session.entries.filter((e) => e.type === 'photo');

  let totalArea = 0;
  let paintGallons = 0;
  for (const m of measurements) {
    totalArea += m.measurement.areaSqft;
    paintGallons += (m.measurement.areaSqft * m.measurement.coats) / PAINT_COVERAGE;
  }

  return {
    measurements,
    notes,
    photos,
    totalArea: Number(totalArea.toFixed(2)),
    paintGallons: Number(paintGallons.toFixed(2)),
    recommendedGallons: Math.ceil(paintGallons),
  };
}

function reportTextFromSummary(session, summary, aiNarrative = '') {
  const lines = [];
  lines.push('Field Estimate Report');
  lines.push('=====================');
  lines.push(`Started: ${session.startedAt}`);
  lines.push(`Completed: ${session.completedAt || nowIso()}`);
  lines.push('');

  if (aiNarrative) {
    lines.push('Overview');
    lines.push('--------');
    lines.push(aiNarrative.trim());
    lines.push('');
  }

  lines.push('Measurement Entries');
  lines.push('-------------------');
  if (!summary.measurements.length) {
    lines.push('No measurements captured.');
  } else {
    summary.measurements.forEach((entry, idx) => {
      const m = entry.measurement;
      const size =
        m.source === 'dimensions'
          ? `${m.lengthFt}ft x ${m.heightFt}ft`
          : `${m.areaSqft} sqft (provided)`;
      const gallons = ((m.areaSqft * m.coats) / PAINT_COVERAGE).toFixed(2);
      lines.push(
        `${idx + 1}. ${m.location} | ${size} | ${m.coats} coats | ${m.areaSqft} sqft | ${gallons} gal`
      );
    });
  }
  lines.push('');

  lines.push('Observations');
  lines.push('------------');
  if (!summary.notes.length && !summary.photos.length) {
    lines.push('No notes or photos logged.');
  } else {
    summary.notes.forEach((n, idx) => lines.push(`${idx + 1}. ${n.text}`));
    if (summary.photos.length) {
      lines.push(`Photos captured: ${summary.photos.length}`);
    }
  }
  lines.push('');

  lines.push('Material Estimate');
  lines.push('-----------------');
  lines.push(`Total measured area: ${summary.totalArea} sqft`);
  lines.push(`Estimated paint needed: ${summary.paintGallons} gallons`);
  lines.push(`Recommended to purchase: ${summary.recommendedGallons} gallons`);
  lines.push(`Coverage assumption: ${PAINT_COVERAGE} sqft per gallon, per coat`);
  lines.push('');
  lines.push('Review before final pricing: prep level, primer needs, trim/doors detail, and labor rate.');

  return lines.join('\n');
}

async function buildNarrativeWithGrok(session, summary) {
  if (!GROK_API_KEY) return '';
  const compactMeasurements = summary.measurements.map((entry) => entry.measurement);
  const payload = {
    startedAt: session.startedAt,
    completedAt: session.completedAt,
    totals: {
      totalArea: summary.totalArea,
      paintGallons: summary.paintGallons,
      recommendedGallons: summary.recommendedGallons,
      coverage: PAINT_COVERAGE,
    },
    measurements: compactMeasurements,
    notes: summary.notes.map((n) => n.text),
    photoCount: summary.photos.length,
  };

  try {
    const response = await fetch('https://api.x.ai/v1/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${GROK_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: GROK_MODEL,
        temperature: 0.2,
        max_tokens: 300,
        messages: [
          {
            role: 'system',
            content:
              'You write concise painting estimate summaries. Include condition observations, scope hints, and risk notes. Keep to 4-6 sentences.',
          },
          {
            role: 'user',
            content: `Create a short field-summary narrative from this JSON:\n${JSON.stringify(payload)}`,
          },
        ],
      }),
    });
    if (!response.ok) return '';
    const data = await response.json();
    return data.choices?.[0]?.message?.content?.trim() || '';
  } catch {
    return '';
  }
}

async function sendLongText(ctx, text) {
  const chunkSize = 3500;
  for (let start = 0; start < text.length; start += chunkSize) {
    await ctx.reply(text.slice(start, start + chunkSize));
  }
}

bot.start(async (ctx) => {
  getSession(ctx.chat.id);
  await ctx.reply(
    [
      'Paint Field Estimator is ready.',
      'Send notes and measurements as you walk the job.',
      '',
      'Examples:',
      '- "Living room wall: 12 x 8 ft, 2 coats, peeling near baseboard"',
      '- "Kitchen ceiling: 180 sqft, 1 coat"',
      '',
      'Commands:',
      '/new - start a fresh estimate',
      '/status - see running totals',
      '/done - generate final report',
    ].join('\n')
  );
});

bot.command('new', async (ctx) => {
  sessions.set(ctx.chat.id, createSession());
  await ctx.reply('Started a new estimate session. Send measurements and observations anytime.');
});

bot.command('status', async (ctx) => {
  const session = getSession(ctx.chat.id);
  const summary = summarizeSession(session);
  await ctx.reply(
    [
      'Current session status:',
      `- Measurements: ${summary.measurements.length}`,
      `- Notes: ${summary.notes.length}`,
      `- Photos: ${summary.photos.length}`,
      `- Total area: ${summary.totalArea} sqft`,
      `- Estimated paint: ${summary.paintGallons} gal (${summary.recommendedGallons} gal recommended)`,
    ].join('\n')
  );
});

bot.command('done', async (ctx) => {
  const session = getSession(ctx.chat.id);
  session.completedAt = nowIso();
  const summary = summarizeSession(session);
  const narrative = await buildNarrativeWithGrok(session, summary);
  const report = reportTextFromSummary(session, summary, narrative);
  await sendLongText(ctx, report);
  await ctx.reply('Report generated. Use /new when you are ready for the next property.');
});

bot.command('help', async (ctx) => {
  await ctx.reply(
    [
      'Send any text note, measurement, or issue you observe.',
      'If your text includes dimensions or sqft, I will log it as a measurement.',
      'Otherwise I store it as an observation note.',
      '',
      'Use /done when walkthrough is complete.',
    ].join('\n')
  );
});

bot.on('photo', async (ctx) => {
  const session = getSession(ctx.chat.id);
  const photos = ctx.message.photo || [];
  const best = photos[photos.length - 1];
  session.entries.push({
    type: 'photo',
    fileId: best?.file_id || null,
    caption: ctx.message.caption || '',
    at: nowIso(),
  });
  await ctx.reply('Photo logged for this estimate.');
});

bot.on('text', async (ctx) => {
  const text = (ctx.message?.text || '').trim();
  if (!text || text.startsWith('/')) return;

  const session = getSession(ctx.chat.id);
  const measurement = extractMeasurement(text);
  if (measurement) {
    session.entries.push({
      type: 'measurement',
      measurement,
      sourceText: text,
      at: nowIso(),
    });
    const gallons = ((measurement.areaSqft * measurement.coats) / PAINT_COVERAGE).toFixed(2);
    await ctx.reply(
      `Measurement logged: ${measurement.location}, ${measurement.areaSqft} sqft, ${measurement.coats} coats (~${gallons} gal).`
    );
    return;
  }

  session.entries.push({
    type: 'note',
    text,
    at: nowIso(),
  });
  await ctx.reply('Observation noted.');
});

bot.catch(async (err, ctx) => {
  console.error('Telegram bot error:', err);
  try {
    await ctx.reply('I hit an error while saving that entry. Please resend.');
  } catch {
    // ignore reply errors
  }
});

await assertTelegramTokenIsOperational(BOT_TOKEN);
await bot.launch();
console.log('Telegram field estimator bot started.');

const shutdown = async (signal) => {
  console.log(`Received ${signal}. Stopping bot.`);
  await bot.stop(signal);
  process.exit(0);
};

process.once('SIGINT', () => {
  shutdown('SIGINT');
});
process.once('SIGTERM', () => {
  shutdown('SIGTERM');
});
