# OST Agent Roadmap (Operator Playbook)

This file is the agent's operating roadmap for On-Screen Takeoff (OST).
Use it as the first reference before any automation run.

## Purpose

- Keep agent behavior consistent across projects.
- Reduce retries by following a fixed sequence.
- Prioritize data that improves takeoff accuracy.

## Core Rule: Ingest Only Useful Pages

After opening a project in OST:

1. Open the `Plan Pages` dropdown.
2. Scroll the list top-to-bottom in order.
3. Select pages that are highlighted in the dropdown.
4. Treat highlighted pages as "has existing takeoff signal".
5. Prioritize those pages for ingestion and analysis.

If no highlighted pages are found, ingest from the first pages in order and mark confidence lower.

## Standard Operating Sequence (Per Project)

1. **Focus OST window**
   - Ensure all clicks are clamped to OST bounds.
   - Do not interact with taskbar.
2. **Open project**
   - Select target project from `Projects` tab.
3. **Collect page candidates**
   - Run Plan Pages highlight scan.
   - Build ordered list of candidate pages.
4. **Capture evidence**
   - For each candidate page: screenshot + OCR pass.
   - Record condition context and any height/finish cues.
5. **Ingest knowledge**
   - Merge into accuracy index domains:
     - conditions/quantities
     - finish taxonomy
     - symbols
     - height notations
     - design signatures
     - OCR glossary
6. **Quality gate**
   - Emit `overall_ok`, review queue items, and blockers.
7. **Blocker handling**
   - Retry transient failures once.
   - Continue with degraded mode if optional inputs are missing.
   - Record open blockers in output artifacts.

## Command Map

Run from workspace root:

```powershell
python "scripts/ost_orchestrator.py" plan-pages-highlight-scan --monitor-index 1 --scroll-steps 12 --capture-highlighted
```

```powershell
python "scripts/ost_orchestrator.py" accuracy-ingestion --project-id "TP-0001"
```

Batch across registry projects:

```powershell
$reg = Get-Content "scripts/ost_training_registry.json" -Raw | ConvertFrom-Json
foreach ($p in $reg.projects) {
  $projectId = [string]$p.training_project_id
  if (-not [string]::IsNullOrWhiteSpace($projectId)) {
    python "scripts/ost_orchestrator.py" accuracy-ingestion --project-id $projectId
  }
}
```

## Required Outputs (Per Run)

- `output/ost-training-lab/plan_pages_highlight_scan_latest.json`
- `output/ost-training-lab/accuracy_knowledge/<project>/accuracy_index_*.json`
- `output/ost-training-lab/accuracy_knowledge/<project>/accuracy_ingestion_report_*.md`
- `output/ost-training-lab/review_queue/accuracy_ingestion_review_queue.json`

## Non-Negotiable Safety Rules

- Emergency pause must remain active.
- Mouse takeover guard must remain active.
- Never click outside OST window bounds.
- If unexpected UI state appears, stop and log blocker instead of guessing.

## Operator Notes Section (Living Rules)

Append new rules here when you coach Maverick:

- "Use highlighted Plan Pages entries as ingestion priority."
- "Prefer ceiling/gwb conditions in phase-1 area logic."
- "Start area traces from clean 90-degree corners when possible."

