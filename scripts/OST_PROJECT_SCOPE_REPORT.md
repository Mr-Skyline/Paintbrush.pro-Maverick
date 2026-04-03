# OST Project Scope Report

This script gives the agent broader project understanding before/alongside Boost.

## What it does

- Scans a project folder for relevant docs (`.pdf`, `.docx`, `.txt`, `.md`, `.csv`, `.json`)
- Extracts painting/wallcover/high-performance product signals
- Detects finish code references (`F-1`, `F-12`, `FINISH 5`)
- Detects unit tokens (`UNIT-A`, `UNIT-B2`, etc.)
- Builds an inferred unit matrix (`unit -> finish codes`)
- Flags likely conflicts (same finish code tied to multiple product families)
- Outputs JSON + Markdown report

## Usage

```bash
python scripts/ost_project_scope_report.py \
  --project-folder "C:\OCS Documents\OST" \
  --output-json "output/ost-project-scope/latest.json" \
  --output-md "output/ost-project-scope/latest.md"
```

## Training Lab integration

`scripts/ost_training_lab.py` now runs this automatically during `run-module` when
`source_project_folder` is set in `scripts/ost_training_registry.json`.

Example project entry:

```json
{
  "training_project_id": "TP-0001",
  "source_project_folder": "C:\\OCS Documents\\OST",
  "source_pdf_path": "G:\\Shared drives\\...\\Set.pdf"
}
```

## Notes

- This is heuristic and intentionally conservative.
- It is meant to surface likely conflicts and missing context quickly.
- You can tighten rules over time with project-specific patterns.
