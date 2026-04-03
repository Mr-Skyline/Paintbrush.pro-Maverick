# OST Project Setup Agent

Automates OST project setup after intake/scope analysis using configurable UI steps.

## Files

- Script: `scripts/ost_project_setup_agent.py`
- Config: `scripts/ost_project_setup_agent.config.json`

## Variables available in step text

- `{{project_name}}`
- `{{project_dir}}`
- `{{plan_pdf}}`
- `{{takeoff_plans_dir}}`
- `{{takeoff_plans_first_file}}`
- `{{timestamp}}`

`plan_pdf` now defaults to the first file found in the `TAKE-OFF PLANS` folder (name-variant tolerant) when present.

Default setup flow includes selecting:
- `training_playground_first_project` (must be a project row under Training Playground, not the Training Playground header row)

## Supported step types

- `click_anchor`
- `double_click_anchor`
- `click_point`
- `double_click_point`
- `hotkey`
- `press`
- `type_text`
- `paste_text`
- `sleep_ms`
- `screenshot`

## Run directly

```powershell
python "scripts\ost_project_setup_agent.py" `
  --config "scripts\ost_project_setup_agent.config.json" `
  --project-name "10th and Sheridan" `
  --project-id "TP-0001" `
  --project-dir "G:\Shared drives\SKYLINE 2026\AI Bids\10th and Sheridan" `
  --plan-pdf "G:\Shared drives\SKYLINE 2026\AI Bids\10th and Sheridan\10th and Sheridan arch plans.pdf" `
  --out-dir "output\ost-project-setup\test" `
  --dry-run
```

## Maverick logging

Setup agent now reports step outcomes to Maverick when enabled in config:

```json
"maverick_logging": {
  "enabled": true,
  "runtime_config_path": "scripts/maverick_runtime.config.json",
  "project_id": ""
}
```

Logged archetypes include:
- `setup-workflow`
- `setup-focus-window`
- `setup-missing-anchor`

## Safety

- `enabled` is `false` by default in config.
- Turn it on only after validating click anchors.
- `--dry-run` records intended actions without clicking.
