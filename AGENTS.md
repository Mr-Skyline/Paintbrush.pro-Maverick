# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Paintbrush Takeoff is a construction on-screen takeoff (OST) tool built with React 18 + Vite + TypeScript + Tailwind + Zustand, Fabric.js canvas, pdf.js, Socket.IO, and an Express backend. No database server is required — persistence is entirely client-side via IndexedDB.

### Running the app

```bash
npm run dev
```

This starts **two processes** via `concurrently`:
- **Vite dev server** on `http://localhost:5173` (frontend)
- **Express + Socket.IO server** on `http://localhost:3000` (backend API)

The Vite dev server proxies `/api` and `/socket.io` to the Express backend.

### Lint / Type-check / Build

- **Type check:** `npx tsc --noEmit`
- **Build:** `npm run build` (runs `tsc --noEmit && vite build`)
- No ESLint config is present in the repo; TypeScript strict mode is the primary static check.

### External API keys (optional)

The app works fully without external API keys. AI voice agent and chat features require keys in `.env` (copy from `.env.example`):
- `GROK_API_KEY` — xAI Grok for chat/agent
- `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` — voice TTS
- `TELEGRAM_BOT_TOKEN` — standalone Telegram bot (`npm run bot:telegram`)

### Key gotchas

- The Express backend returns 404 on `GET /` in dev mode — this is expected; it only serves API routes (`/api/*`) and Socket.IO. In production mode it serves the built `dist/` folder.
- Electron desktop mode (`npm run dev:desktop`) requires a display and is not usable in headless cloud environments.
- Python scripts under `scripts/` are auxiliary automation tooling (OCR, training, orchestration) and are not part of the core web app runtime.
