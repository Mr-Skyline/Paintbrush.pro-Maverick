# Paintbrush Takeoff Agent (Standalone CV Pipeline)

This package implements a standalone blueprint takeoff pipeline:

1. Input file (PDF/image) -> preprocess
2. CV detection (walls/rooms/counts)
3. Post-process + quantity calculation
4. Export JSON + CSV for downstream handoff

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r takeoff_agent/requirements.txt
python -m takeoff_agent.main \
  --input path/to/plan.png \
  --out ./output/takeoff \
  --save-debug-images \
  --save-overlays \
  --enable-supabase-handoff
```

## Batch runner

Run multiple jobs from a queue JSON file:

```bash
python -m takeoff_agent.batch_runner \
  --queue takeoff_agent/batch_queue.example.json \
  --continue-on-error
```

Queue format:

```json
[
  {
    "input": "/abs/path/plan1.png",
    "project_id": "job-001",
    "out": "/abs/path/output/job-001",
    "save_overlays": true,
    "enable_supabase_handoff": true
  }
]
```

Each run writes a deterministic `idempotency_key` into:

- `takeoff-results.json`
- `handoff/<project>-supabase-handoff.json`

## Runtime reliability features

- Detection retry for low-confidence pages.
- Structured logs in `logs/run.log` and `logs/errors.jsonl`.
- Optional overlay rendering.
- Optional Supabase handoff that never blocks local completion.

## Optional environment variables

Use these for direct Supabase inserts:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (preferred) or `SUPABASE_ANON_KEY`
- `SUPABASE_TAKEOFF_TABLE` (default: `estimates`)
- `SUPABASE_TAKEOFF_BUCKET` (default: `takeoffs`)

## Outputs

- `takeoff-results.json`
- `takeoff-results.csv`

The JSON includes walls, rooms, counts, scale/confidence metadata, and idempotency.

## Notes

- Current detection uses a robust OpenCV baseline with optional YOLO path.
- YOLO config supports:
  - `model_path` (preferred)
  - `wall_model_path` (legacy alias)
- Runtime error handling writes structured entries to `output/.../logs/errors.jsonl`.
