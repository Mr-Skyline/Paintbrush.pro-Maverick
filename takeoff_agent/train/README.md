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

### Incremental document-folder ingestion (idempotent)

Point this at a folder you keep populating with new files. It processes only:

- PDF (`.pdf`)
- Word (`.doc`, `.docx`)

Excel files are intentionally ignored.

It only processes new or changed documents and tracks state in a local ingest DB:

```bash
python -m takeoff_agent.train.cli ingest-pdf-folder \
  --source-dir /workspace/data/training/raw_pdfs \
  --dataset-root /workspace/takeoff_agent/train/datasets/fresh_start \
  --split train \
  --recursive
```

Optional knobs:

- `--limit-files 25` to process only the first N pending files in a pass
- `--dpi 300` for conversion quality
- `--force` to reprocess unchanged files
- `--clean-removed` to remove generated pages when source docs are deleted

Re-running the same command is safe; unchanged PDFs are skipped automatically.

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
python -m takeoff_agent.train.cli train-yolo-walls \
  --data-yaml /workspace/takeoff_agent/train/datasets/fresh_start/data.yaml \
  --model yolo11n.pt \
  --epochs 50 \
  --imgsz 1024 \
  --project-dir /workspace/takeoff_agent/train/runs \
  --run-name walls_baseline
```

Outputs under run folder:

- `train_job.json` (parameters + detected best weight path)
- Ultralytics `weights/best.pt` (if training succeeds)

## Promote trained model into runtime config

Copy selected weights into `takeoff_agent/models/` and patch `takeoff_agent/config.yaml`
to enable YOLO wall inference:

```bash
python -m takeoff_agent.train.cli promote-model \
  --weights /workspace/takeoff_agent/train/runs/walls_baseline/weights/best.pt \
  --config-path /workspace/takeoff_agent/config.yaml \
  --enable-yolo
```

This updates:

- `detection.walls.yolo.enabled = true`
- `detection.walls.yolo.model_path = <copied path>`

### Notes

- Upload is best-effort; local dataset initialization always works.
- This flow intentionally starts from scratch and avoids existing run artifacts.

