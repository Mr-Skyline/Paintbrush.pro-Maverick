# Cursor Cloud Agents Setup

This repo is prepared for Cursor Cloud Agent execution on branch `battleship-grok-review`.

## 1) Local Preflight

Run:

```powershell
pwsh "scripts/cloud_agent_preflight.ps1"
```

If you keep secrets in a dedicated file:

```powershell
copy ".env.cloud.template" ".env.cloud"
pwsh "scripts/cloud_agent_preflight.ps1" -EnvFile ".env.cloud"
```

## 2) Push to GitHub

Cloud agents execute from remote git state, so push branch first.

## 3) Open Cursor Cloud Agents

- Connect GitHub if not already connected.
- Select repository: `Mr-Skyline/Paintbrush.pro-Maverick`
- Select branch: `battleship-grok-review`
- Start an agent task with your objective (build/deploy/test).

## 4) Cloud Environment Variables

Provide these in cloud env/secret settings:

- `GROK_API_KEY`
- `TAKEOFF_CV_API_URL`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` (when DB writes are needed)
- Optional:
  - `HF_TOKEN`
  - `HF_TAKEOFF_ENDPOINT`
  - `RAILWAY_TOKEN`
  - `ELEVENLABS_API_KEY`
  - `ELEVENLABS_VOICE_ID`

## 5) Recommended Cloud Task Order

1. Run `npm run build`
2. Run Python CV health checks (`takeoff_agent/main.py`, `/health`)
3. Run end-to-end API checks:
   - `/api/takeoff/process-upload`
   - `/api/sidekick/chat`
   - `/api/schedule/upsert`

## 6) Deployment Hand-off

Use:

- `docs/deployment/railway-takeoff-service.md`
- `scripts/deploy_railway_takeoff.ps1`

to deploy CV service and wire `TAKEOFF_CV_API_URL`.
