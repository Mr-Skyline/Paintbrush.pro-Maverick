import 'dotenv/config';
import express from 'express';
import http from 'http';
import path from 'path';
import { fileURLToPath } from 'url';
import { Server } from 'socket.io';
import { AGENT_TOOLS } from './agentTools.mjs';
import multer from 'multer';
import { processBlueprintWithCv } from './takeoffCvProxy.mjs';
import {
  saveSidekickChat,
  saveTakeoffResult,
  upsertScheduleEvent,
} from './supabaseGateway.mjs';
import { enqueueReview, logDecision } from './auditLog.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: true } });

const PORT = process.env.PORT || 3000;
const DIST = path.join(__dirname, '..', 'dist');
const isProd = process.env.NODE_ENV === 'production';

app.use(express.json({ limit: '4mb' }));
const upload = multer({ limits: { fileSize: 25 * 1024 * 1024 } });

app.post('/api/tts', async (req, res) => {
  const key = process.env.ELEVENLABS_API_KEY;
  const voiceId = req.body.voice_id || process.env.ELEVENLABS_VOICE_ID;
  const text = (req.body.text || '').toString().slice(0, 2500);
  if (!key || !voiceId) {
    res
      .status(503)
      .json({
        error:
          'ElevenLabs not configured (.env ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID)',
      });
    return;
  }
  if (!text.trim()) {
    res.status(400).json({ error: 'Missing text' });
    return;
  }
  try {
    const upstream = await fetch(
      `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}/stream`,
      {
        method: 'POST',
        headers: {
          'xi-api-key': key,
          'Content-Type': 'application/json',
          Accept: 'audio/mpeg',
        },
        body: JSON.stringify({
          text,
          model_id: 'eleven_turbo_v2',
        }),
      }
    );
    if (!upstream.ok) {
      const errText = await upstream.text();
      res.status(upstream.status).json({ error: errText || upstream.statusText });
      return;
    }
    res.setHeader('Content-Type', 'audio/mpeg');
    const reader = upstream.body.getReader();
    const pump = async () => {
      const { done, value } = await reader.read();
      if (done) {
        res.end();
        return;
      }
      res.write(Buffer.from(value));
      await pump();
    };
    await pump();
  } catch (e) {
    res.status(500).json({ error: String(e.message || e) });
  }
});

/** Grok (xAI) — estimator brain for voice + Boost assist */
app.post('/api/chat', async (req, res) => {
  const key = process.env.GROK_API_KEY || process.env.XAI_API_KEY;
  const system = (req.body.system || '').toString();
  const messages = req.body.messages;
  if (!key) {
    res.json({
      reply:
        'Grok API key missing. Add GROK_API_KEY to .env for live estimator chat.',
    });
    return;
  }
  if (!Array.isArray(messages)) {
    res.status(400).json({ error: 'messages[] required' });
    return;
  }
  try {
    const r = await fetch('https://api.x.ai/v1/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: process.env.GROK_MODEL || 'grok-2-latest',
        messages: [
          { role: 'system', content: system || 'You are a helpful assistant.' },
          ...messages,
        ],
        temperature: 0.4,
        max_tokens: 1024,
      }),
    });
    const data = await r.json();
    if (!r.ok) {
      res.status(r.status).json({
        error: data.error?.message || JSON.stringify(data),
      });
      return;
    }
    const reply = data.choices?.[0]?.message?.content?.trim();
    res.json({ reply: reply || 'No content.' });
  } catch (e) {
    res.status(500).json({ error: String(e.message || e) });
  }
});

/**
 * Grok agent step — OpenAI-compatible tools; client executes tool_calls in the browser.
 */
app.post('/api/agent/step', async (req, res) => {
  const key = process.env.GROK_API_KEY || process.env.XAI_API_KEY;
  if (!key) {
    res.json({
      keyMissing: true,
      error: 'GROK_API_KEY missing',
      message: null,
    });
    return;
  }
  const system = (req.body.system || '').toString();
  const messages = req.body.messages;
  if (!Array.isArray(messages)) {
    res.status(400).json({ error: 'messages[] required', message: null });
    return;
  }
  try {
    const r = await fetch('https://api.x.ai/v1/chat/completions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: process.env.GROK_MODEL || 'grok-2-latest',
        messages: [
          { role: 'system', content: system || 'You are a helpful agent.' },
          ...messages,
        ],
        tools: AGENT_TOOLS,
        tool_choice: 'auto',
        temperature: 0.25,
        max_tokens: 4096,
      }),
    });
    const data = await r.json();
    if (!r.ok) {
      res.status(r.status).json({
        error: data.error?.message || JSON.stringify(data),
        message: null,
      });
      return;
    }
    const choice = data.choices?.[0];
    const msg = choice?.message;
    if (!msg) {
      res.json({ error: 'No message in response', message: null });
      return;
    }
    res.json({
      message: msg,
      finish_reason: choice.finish_reason,
    });
  } catch (e) {
    res.status(500).json({ error: String(e.message || e), message: null });
  }
});

app.get('/api/takeoff/health', (_req, res) => {
  res.json({
    ok: true,
    cvApi: process.env.TAKEOFF_CV_API_URL ? 'configured' : 'mock',
    supabase: process.env.SUPABASE_URL ? 'configured' : 'not-configured',
  });
});

app.post('/api/takeoff/process-upload', upload.single('file'), async (req, res) => {
  try {
    const projectId = String(req.body.projectId || 'local-project').trim();
    const file = req.file;
    if (!file) {
      res.status(400).json({ error: 'Missing file upload' });
      return;
    }
    const result = await processBlueprintWithCv({
      projectId,
      sourceName: file.originalname,
      mimeType: file.mimetype,
      fileBuffer: file.buffer,
    });
    logDecision('takeoff_processed', {
      projectId,
      sourceName: file.originalname,
      confidence: result.confidence,
      walls: result.walls?.length ?? 0,
      rooms: result.rooms?.length ?? 0,
      auditId: result.auditId ?? null,
    });
    if ((result.confidence ?? 0) < 0.9 || result.needsReview) {
      enqueueReview({
        projectId,
        sourceName: file.originalname,
        confidence: result.confidence ?? 0,
        reason: 'low_confidence',
        result,
      });
    }
    const save = await saveTakeoffResult(result);
    res.json({
      ...result,
      persisted: save.ok,
      persistenceError: save.error,
    });
  } catch (error) {
    logDecision('takeoff_error', {
      error: String(error?.message || error),
      endpoint: '/api/takeoff/process-upload',
    });
    res.status(500).json({ error: String(error?.message || error) });
  }
});

app.post('/api/sidekick/chat', async (req, res) => {
  const projectId = String(req.body?.projectId || 'local-project').trim();
  const userText = String(req.body?.message || '').trim();
  if (!userText) {
    res.status(400).json({ error: 'Missing message' });
    return;
  }

  const key = process.env.GROK_API_KEY || process.env.XAI_API_KEY;
  let reply = '';
  if (key) {
    try {
      const model = process.env.GROK_MODEL || 'grok-2-latest';
      const upstream = await fetch('https://api.x.ai/v1/chat/completions', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${key}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model,
          messages: [
            {
              role: 'system',
              content:
                'You are Paintbrush Sidekick. Keep answers concise, practical, and grounded in latest takeoff run context.',
            },
            { role: 'user', content: userText },
          ],
          temperature: 0.25,
          max_tokens: 500,
        }),
      });
      const data = await upstream.json();
      if (!upstream.ok) {
        throw new Error(data?.error?.message || JSON.stringify(data));
      }
      reply = String(data?.choices?.[0]?.message?.content || '').trim();
    } catch (error) {
      reply = `Sidekick fallback: ${String(error?.message || error)}`;
    }
  } else {
    reply =
      'Sidekick is running in local fallback mode (no GROK key). Detection completed and schedule can still be updated.';
  }
  await saveSidekickChat(projectId, userText, reply);
  logDecision('chat_reply', { projectId, userText, reply });
  res.json({ reply });
});

app.post('/api/schedule/upsert', async (req, res) => {
  const projectId = String(req.body?.projectId || '').trim();
  const title = String(req.body?.title || '').trim();
  const startsAtIso = String(req.body?.startsAtIso || '').trim();
  const notes = String(req.body?.notes || '').trim();
  if (!projectId || !title || !startsAtIso) {
    res.status(400).json({ error: 'projectId, title, startsAtIso are required' });
    return;
  }
  const out = await upsertScheduleEvent({
    projectId,
    title,
    startsAtIso,
    notes,
  });
  if (!out.ok && !out.skipped) {
    res.status(500).json({ error: out.error || 'Could not persist schedule' });
    return;
  }
  logDecision('schedule_upsert', {
    projectId,
    title,
    startsAtIso,
    saved: out.ok,
    skipped: Boolean(out.skipped),
  });
  res.json({ ok: true });
});

io.on('connection', (socket) => {
  socket.on('object:add', (payload) => {
    socket.broadcast.emit('object:add', { ...payload, from: socket.id });
  });
  socket.on('object:modify', (payload) => {
    socket.broadcast.emit('object:modify', { ...payload, from: socket.id });
  });
  socket.on('object:remove', (payload) => {
    socket.broadcast.emit('object:remove', { ...payload, from: socket.id });
  });
  socket.on('pdf:state', (payload) => {
    socket.broadcast.emit('pdf:state', { ...payload, from: socket.id });
  });
  socket.on('bot:boost:request', (payload) => {
    socket.broadcast.emit('bot:boost:request', { ...payload, from: socket.id });
  });
});

if (isProd) {
  app.use(express.static(DIST));
  app.get('*', (_req, res) => {
    res.sendFile(path.join(DIST, 'index.html'));
  });
}

server.listen(PORT, () => {
  console.log(`API + Socket.IO http://localhost:${PORT}`);
  if (isProd) console.log(`Serving ${DIST}`);
});
