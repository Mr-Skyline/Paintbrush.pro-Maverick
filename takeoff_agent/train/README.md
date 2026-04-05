This folder contains model-training and dataset utilities for `takeoff_agent`.

## Fresh start workflow (recommended)

Use a clean dataset scaffold (no legacy run ingestion):

```bash
python -m takeoff_agent.train.cli init-fresh-dataset \
  --dataset-root /workspace/takeoff_agent/train/datasets/fresh_start \
  --project-name "Paintbrush.pro"
```

This creates:

- `images/train|val|test`
- `labels/train|val|test`
- `manifest.json`
- `labels_template.txt` with class/id guidance

Add your first fresh images into one split folder (for example `images/train`),
and create matching YOLO label files in `labels/train`.

### Upload fresh images to Roboflow

```bash
python -m takeoff_agent.train.cli upload-images \
  --images-dir /workspace/takeoff_agent/train/datasets/fresh_start/images/train \
  --split train \
  --workspace your-workspace-slug \
  --project your-project-slug \
  --api-key $ROBOFLOW_API_KEY
```

Dry-run first (no API calls):

```bash
python -m takeoff_agent.train.cli upload-images \
  --images-dir /workspace/takeoff_agent/train/datasets/fresh_start/images/train \
  --dry-run
```

### Required values for live upload

- `ROBOFLOW_API_KEY`
- Roboflow project slug (or set `ROBOFLOW_PROJECT`)
- Optional workspace slug (or set `ROBOFLOW_WORKSPACE`)

### Notes

- Upload is best-effort; local dataset initialization always works.
- This flow intentionally starts from scratch and avoids existing run artifacts.
