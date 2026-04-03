# OST Project Intake

Auto-organizes project files and builds scope reports when new files land in the project root.

## What it does

- Watches a configured root (default: `G:\Shared drives\SKYLINE 2026\AI Bids`)
- Detects project folders with new/updated files
- Moves/renames files into:
  - `_organized/plans`
  - `_organized/specifications`
  - `_organized/schedules`
  - `_organized/addenda`
  - `_organized/submittals`
  - `_organized/other`
- Writes reports to `_reports`:
  - `intake_manifest.json`
  - `project_scope_intel.json`
  - `project_scope_intel.md`
  - `scope_profile.json` (when a plan PDF is found)
  - `ost_setup/setup_result.json` (when setup stage is enabled)

Plan file selection rule used by intake/setup:
- If a `TAKE-OFF PLANS` folder exists in the project folder, use the first file in that folder.
- Otherwise fall back to best-matching plan PDF in the project.

## Config

File: `scripts/ost_project_intake.config.json`

Important fields:

- `allowed_roots`: folders the script is allowed to modify
- `watch_root`: root folder to monitor
- `auto_apply`: `true` to move/rename, `false` for analysis only
- `poll_seconds`: watch loop interval
- `min_idle_seconds_before_process`: wait for downloads to finish
- `ost_setup.enabled`: run OST setup stage after intake/scope
- `ost_setup.config_path`: OST setup config JSON
- `ost_setup.script_path`: OST setup runner script

## Usage

One pass:

```powershell
python "scripts\ost_project_intake.py" --once
```

Dry run:

```powershell
python "scripts\ost_project_intake.py" --once --dry-run
```

Watch continuously:

```powershell
python "scripts\ost_project_intake.py" --watch
```

Filter to one project:

```powershell
python "scripts\ost_project_intake.py" --once --project-filter "10th and Sheridan"
```

## OST setup stage

Script: `scripts/ost_project_setup_agent.py`  
Config: `scripts/ost_project_setup_agent.config.json`

The setup agent supports configurable UI steps:
- click anchors
- click points
- hotkeys / key presses
- type/paste text with variables:
  - `{{project_name}}`
  - `{{project_dir}}`
  - `{{plan_pdf}}`

Safety defaults:
- Intake enables the setup stage call.
- Setup config itself is `enabled: false` by default until you confirm anchor calibration.
