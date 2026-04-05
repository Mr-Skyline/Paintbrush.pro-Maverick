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

## Generate YOLO data.yaml

```bash
python -m takeoff_agent.train.cli write-yolo-config \
  --dataset-root /workspace/takeoff_agent/train/datasets/fresh_start \
  --out /workspace/takeoff_agent/train/datasets/fresh_start/data.yaml
```

## Evaluate local run quality

Creates a local report from existing `output/*/takeoff-results.json` runs:

```bash
python -m takeoff_agent.train.cli evaluate-runs \
  --runs-root /workspace/output \
  --out-dir /workspace/takeoff_agent/train/eval/latest \
  --min-confidence 0.9
```

Outputs:

- `report.json`
- `summary.csv`

## Run a YOLO wall training job

This command launches an Ultralytics training run and writes run metadata:

```bash
python -m takeoff_agent.train.cli run-yolo-train \
  --data-yaml /workspace/takeoff_agent/train/datasets/fresh_start/data.yaml \
  --model yolo11n.pt \
  --epochs 50 \
  --imgsz 1024 \
  --out-dir /workspace/takeoff_agent/train/runs \
  --run-name walls_baseline
```

Outputs under run folder:

- `train_job.json` (parameters + detected best weight path)
- Ultralytics `weights/best.pt` (if training succeeds)

## Promote trained model into runtime config

Copy selected weights into `takeoff_agent/models/` and patch `takeoff_agent/config.yaml`
to enable YOLO wall inference:

```bash
python -m takeoff_agent.train.cli promote-wall-model \
  --weights /workspace/takeoff_agent/train/runs/walls_baseline/weights/best.pt \
  --config /workspace/takeoff_agent/config.yaml
```

This updates:

- `detection.walls.yolo.enabled = true`
- `detection.walls.yolo.model_path = <copied path>`

### Notes

- Upload is best-effort; local dataset initialization always works.
- This flow intentionally starts from scratch and avoids existing run artifacts.

## Prepare YOLO training metadata

After you add images + labels, generate a YOLO dataset yaml:

```bash
python -m takeoff_agent.train.cli generate-yolo-yaml \
  --dataset-root /workspace/takeoff_agent/train/datasets/fresh_start
```

This writes:

- `yolo_data.yaml` (train/val/test image paths + class names)

## Evaluate takeoff outputs (local harness)

Generate a quality report from one or more existing run outputs:

```bash
python -m takeoff_agent.train.cli eval-runs \
  --runs-root /workspace/output \
  --out-dir /workspace/takeoff_agent/train/eval/latest \
  --confidence-threshold 0.90
```

This writes:

- `report.json`
- `summary.csv`
