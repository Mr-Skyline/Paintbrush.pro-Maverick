# OST Training Lab CLI

This CLI executes and scores training attempts using your OST training playground setup.

## 1) Initialize registry with 21 projects

```powershell
cd "C:\Users\travi\OneDrive\Documents\Paintbrush.pro"
python "scripts\ost_training_lab.py" init-registry --count 21
```

Creates/updates:
- `scripts/ost_training_registry.json`

## 2) Run a training module attempt

Current automated modules:
- `T06-boost-open-run-verify-L2`
- `T07-boost-option-presets-L2`

Before each module run, the lab now performs grouping preselection using:
- `scripts/ost_grouping_selector.py`
- optional `preferred_unit_label` in `scripts/ost_training_registry.json`

It can also run full PDF scope profiling first (if configured):
- `scripts/ost_scope_profiler.py`
- `source_pdf_path` in `scripts/ost_training_registry.json`

It now supports fuzzy folder/PDF discovery when explicit paths are not set:
- `discovery_root_folder` (defaults to `G:\Shared drives\SKYLINE 2026\AI Bids`)
- `project_name` + optional `project_aliases`
- handles abbreviations/misspellings with token + sequence matching

Example:

```powershell
python "scripts\ost_training_lab.py" run-module --module-id "T06-boost-open-run-verify-L2" --project-id "TP-0001"
```

Preview what the resolver will pick:

```powershell
python "scripts\ost_training_lab.py" discover-project-context --project-id "TP-0001"
```

Outputs:
- runs Boost agent once,
- scores the attempt,
- writes report to:
  - `output/ost-training-lab/attempt_ATT-<timestamp>.json`

## 3) View dashboard

```powershell
python "scripts\ost_training_lab.py" dashboard --last 10
```

Shows:
- pass rate,
- average score,
- latest attempts summary.

## Optional: target specific unit type per training project

In `scripts/ost_training_registry.json`, set:

```json
"preferred_unit_label": "unit-b2"
```

When present, grouping selector prioritizes that unit type before Boost run.

## Optional: source PDF path per project

```json
"source_pdf_path": "G:\\Shared drives\\...\\Your Plan Set.pdf"
```

When present, each run records inferred work packages and scope priorities.

## Optional: fuzzy project discovery fields

```json
"discovery_root_folder": "G:\\Shared drives\\SKYLINE 2026\\AI Bids",
"project_aliases": ["Residence Inn Denver", "Residence Inn Den", "RI Denver"]
```

When `source_project_folder` or `source_pdf_path` is blank, the lab auto-resolves likely matches.
