# OST Boost Agent (Local Black-Box)

This runner automates only the licensed OST Boost UI flow on your machine.
It executes a strict 4-step sequence:
1. Open Boost
2. Set Boost options
3. Run Takeoff Boost
4. Verify + record evidence

If enabled, a Step 0 preflight can auto-run a scale correction click sequence when Boost reports
"must set the correct scale".

## 1) Install Python deps

```powershell
pip install pyautogui pygetwindow mss pillow opencv-python pytesseract
```

If OCR returns empty text, also install Tesseract OCR in Windows and ensure it is on `PATH`.
If Tesseract is not installed, the script still runs and marks OCR as skipped in the log.

## 2) Create config

```powershell
copy scripts\ost_boost_agent.config.example.json scripts\ost_boost_agent.config.json
```

By default the agent reads `scripts/ost_ui_atlas.json` when `use_ui_atlas` is true.
Use `scripts/ost_ui_mapper.py` to keep those anchors updated.

## 3) Calibrate click points

Open OST on your target monitor, keep the same layout, then:

```powershell
python scripts\ost_boost_agent.py calibrate --config scripts\ost_boost_agent.config.json
```

You will be asked to place your mouse over:
- `boost_button`
- `boost_run_button`

## 4) Run Boost automation

```powershell
python scripts\ost_boost_agent.py run --config scripts\ost_boost_agent.config.json
```

Optional project scoping for Maverick logs:

```powershell
python scripts\ost_boost_agent.py run --config scripts\ost_boost_agent.config.json --project-id "TP-0001"
```

Evidence output is written to:

`output/ost-boost-agent/<timestamp>/`

with:
- `01_before.png`
- `02_after_open.png`
- `03_after_run.png`
- `run_log.json`

`run_log.json` includes:
- `status.step_status.step1_open_boost`
- `status.step_status.step2_set_options`
- `status.step_status.step3_run`
- `status.step_status.step4_verify`
- `status.failed_step` (step number when strict mode fails)
- `status.open_changed` (dialog open visual change check)
- `status.run_changed` (run-area visual change check)
- `status.ocr_available`
- `status.ocr_pass`

## Optional: preset Boost option clicks (Step 2)

In `scripts/ost_boost_agent.config.json`, add global screen points:

```json
"boost_option_clicks": [
  { "x": 3000, "y": 740 },
  { "x": 3042, "y": 780 }
]
```

These clicks are executed after Boost dialog opens and before Run.

## Optional: auto-scale preflight (Step 0)

When Boost shows a scale warning, the agent can:
1) close Boost,
2) click a configured scale workflow,
3) reopen Boost and re-check warning.

Config example:

```json
"auto_scale_preflight": {
  "enabled": true,
  "max_cycles": 1,
  "scale_clicks": [
    { "x": 2470, "y": 92, "wait_ms": 250 },
    { "x": 2470, "y": 122, "wait_ms": 250 },
    { "x": 2750, "y": 680, "wait_ms": 500 }
  ]
}
```

These are global screen coordinates on your fixed setup.

## Maverick auto-logging integration

`ost_boost_agent.py` now logs workflow steps to Maverick automatically.

Configure in `scripts/ost_boost_agent.config.json`:

```json
"maverick_logging": {
  "enabled": true,
  "runtime_config_path": "scripts/maverick_runtime.config.json",
  "project_id": "TP-0001"
}
```

Behavior:
- Boost focus/open/run/verify failures are logged as Maverick failures.
- Run-button failures are logged with archetype `boost-run-click`.
- Successful runs reset failure counters for the run-click archetype.
- After 10 failures, Maverick coach mode request is generated automatically.

## Safety notes

- Keep OST on the same monitor and window state for repeatability.
- Move mouse to a top-left screen corner to trigger PyAutoGUI failsafe stop.
- This workflow does not reverse-engineer OST internals; it is black-box UI control only.
