# Paintbrush Autonomous Build Notes

## Core Mission

- Keep the takeoff flow stable end-to-end: upload -> detect -> chat -> schedule.
- Preserve existing Battleship lab behavior for training and replay experiments.
- Prefer additive changes that do not break invoice desktop workflows.

## Implementation Rules

- Use `src/components/TakeoffSidekickPanel.tsx` as the primary UI entrypoint for the autonomous sidekick.
- Use `server/index.js` for API composition and persistence adapters.
- Route CV inference through `TAKEOFF_CV_API_URL`; if missing, keep mock fallback functional.
- Persist results when Supabase credentials exist; degrade gracefully when they do not.

## Testing Rules

- Frontend changes: run `npm run build`.
- Server/API changes: run `npm run dev:server` and verify `/api/takeoff/health`.
- Python CV changes: run `python takeoff_agent/main.py` then POST `/api/v1/takeoff/process`.

## Deferred / Later Project Bucket

- Battleship reinforcement tournament enhancements stay on `battleship-grok-review`.
- OST desktop automation scripts under `scripts/ost_*` remain legacy training assets.
- Potential future extraction: separate this repo into `paintbrush-app` and `takeoff-cv-service`.
