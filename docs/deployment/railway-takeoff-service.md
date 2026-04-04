# Railway Deployment Runbook (Takeoff CV Service)

## Service Root

- `takeoff_agent/`

## Prerequisites

- Railway project created
- `RAILWAY_TOKEN` available in environment

## Deploy

```bash
cd takeoff_agent
npx @railway/cli login --token $RAILWAY_TOKEN
npx @railway/cli up --detach
```

## Configure Env Vars

- `PORT=8000`
- Optional model keys:
  - `HF_TOKEN`
  - `HF_TAKEOFF_ENDPOINT`

## Verify

```bash
npx @railway/cli domain
curl https://<domain>/health
```

## App Server Wiring

Set in main app `.env`:

```text
TAKEOFF_CV_API_URL=https://<domain>
```

Then restart app server and check:

```bash
curl http://localhost:3000/api/takeoff/health
```
