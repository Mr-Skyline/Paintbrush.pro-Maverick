# Paintbrush Takeoff Agent (Standalone CV Pipeline)

This package implements a **standalone blueprint takeoff pipeline**:

1. Input file (PDF/image) → preprocess
2. CV detection (walls/rooms/counts)
3. Post-process + quantity calculation
4. Export JSON + CSV for downstream handoff

## Files

- `main.py` — entry point and export wiring
- `preprocess.py` — input normalization, scale detection, denoise
- `detection.py` — baseline CV detection (line/room/symbol)
- `postprocess.py` — geometry cleanup + quantity calculations
- `config.yaml` — thresholds and defaults
- `requirements.txt` — Python dependencies

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

## Runtime reliability features

- Detection retry: if page confidence is below configured threshold, the page is retried with a downscaled image.
- Structured runtime log files: per-run `logs/run.log` and `logs/errors.jsonl`.
- Optional overlay rendering: annotated image output with walls/rooms/counts.
- Optional Supabase handoff: writes handoff payload under `handoff/` and attempts direct insert only when `SUPABASE_URL` + key are available. Local runs never hard-fail on handoff.

## Optional environment variables

Set these only when enabling direct Supabase inserts:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (preferred) or `SUPABASE_ANON_KEY`

## Outputs

- `takeoff-results.json`
- `takeoff-results.csv`

The JSON contains:

- `walls`: line segments + LF
- `rooms`: polygons + SF
- `counts`: symbol counts by class
- `meta`: source, page, scale, confidence

## Notes

- Current detection is a robust baseline using OpenCV primitives and heuristics.
- `ultralytics`/`paddleocr` are included in dependencies for incremental migration to trainable detectors/OCR-based scale detection.
- YOLO integration is optional and activated when model paths are configured in `config.yaml`.
- YOLO config supports both keys for compatibility:
  - `model_path` (preferred)
  - `wall_model_path` (legacy alias)
- Error handling writes structured logs to `output/.../logs/errors.jsonl`.
