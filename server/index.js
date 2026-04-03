import 'dotenv/config';
import express from 'express';
import http from 'http';
import path from 'path';
import { fileURLToPath } from 'url';
import { Server } from 'socket.io';
import { AGENT_TOOLS } from './agentTools.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: true } });

const PORT = process.env.PORT || 3000;
const DIST = path.join(__dirname, '..', 'dist');
const isProd = process.env.NODE_ENV === 'production';

app.use(express.json({ limit: '4mb' }));

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
