# Symbol Knowledge Pipeline

Maverick can now build a local symbol library from open blueprint datasets and query likely symbol classes from a cropped image.

## Commands

Ingest a labeled dataset (folder-per-class):

`python scripts/ost_orchestrator.py symbol-knowledge-ingest --project-id TP-0001 --dataset-root "C:\path\to\dataset" --dataset-name floorplancad`

Run a safety-only scan first (recommended):

`python scripts/ost_orchestrator.py dataset-safety-scan --dataset-root "C:\path\to\dataset" --report-json "output/ost-training-lab/symbol_knowledge/TP-0001/safety_scan.json"`

Query one symbol crop against the built index:

`python scripts/ost_orchestrator.py symbol-knowledge-query --image "C:\path\to\symbol_crop.png" --index-json "output/ost-training-lab/symbol_knowledge/TP-0001/symbol_index_latest.json" --top-k 5`

Build merged finish knowledge (symbols + height notations + design-set signatures):

`python scripts/ost_orchestrator.py finish-knowledge-index-build --project-id TP-0001`

## Dataset Layout

Expected input layout is class-by-folder:

- `dataset_root/door/*.png`
- `dataset_root/window/*.png`
- `dataset_root/sink/*.png`
- `dataset_root/toilet/*.png`

The first directory under `dataset_root` is treated as the `symbol_class`.

## Output

Ingest creates:

- `output/ost-training-lab/symbol_knowledge/<project_id>/embeddings_<dataset>_<timestamp>.jsonl`
- `output/ost-training-lab/symbol_knowledge/<project_id>/symbol_index_<dataset>_<timestamp>.json`
- `output/ost-training-lab/symbol_knowledge/<project_id>/symbol_index_latest.json`

The index stores class prototypes (`prototype_embedding`) and sample paths for quick nearest-match lookup.

## Safety And Quarantine

- Ingestion now runs a dataset safety scan by default.
- Blocked file types (executables/scripts) fail ingestion.
- Warned files (unknown extensions, archives, oversized files) require `--allow-warnings` to continue.
- Images are copied into a quarantine staging root before embeddings are built.

## Notes

- This is a lightweight nearest-prototype baseline for rapid iteration.
- It is designed to be integrated into `count` condition flows so Maverick can decide when a detected frame/symbol implies doors, windows, sinks, toilets, etc.
