# OST Scope Profiler

Profiles a full PDF plan set to infer scope of work before takeoff execution.

## Run

```powershell
cd "C:\Users\travi\OneDrive\Documents\Paintbrush.pro"
python "scripts\ost_scope_profiler.py" --pdf "C:\path\to\plans.pdf"
```

Output:
- `output/ost-scope-profiler/latest.json` (or custom `--output`)

## What it extracts

- Page role hints (`plan_view`, `rcp_view`, `finish_schedule`, etc.)
- Work package recommendations (`walls-linear`, `ceiling-area`, `doors-count`, ...)
- Repeated unit token hints from page text
- Boost priority hints based on detected page roles

## Training lab integration

Set `source_pdf_path` for each project in:
- `scripts/ost_training_registry.json`

When present, `ost_training_lab.py run-module` will run scope profiling first
and attach scope outputs to each attempt report.
