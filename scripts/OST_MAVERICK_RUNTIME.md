# Maverick Runtime

Always-on runtime supervisor for Paintbrush + OST automation.

## Files

- `scripts/maverick_runtime.py`
- `scripts/maverick_runtime.config.json`

## What it does

- Starts required dependencies in a strict sequence.
- Blocks Maverick activation until all dependencies are healthy.
- Watches dependency health continuously.
- On failure, recovers dependency first, then re-enables Maverick.
- Logs all runtime events and step outcomes.
- Tracks failures by workflow archetype and triggers coaching at 10 failures.
- Stores conversation history and generates "since last time" summaries.
- Enforces `suggest-only` update policy via proposal artifacts.

## Run

From repository root:

```powershell
python "scripts\maverick_runtime.py" --config "scripts\maverick_runtime.config.json" always-on
```

or through the orchestrator:

```powershell
python "scripts\ost_orchestrator.py" maverick-always-on
```

## Conversation

```powershell
python "scripts\ost_orchestrator.py" maverick-chat --project "TP-0001" --message "Maverick, what changed since last time?"
```

## Summary delta

```powershell
python "scripts\ost_orchestrator.py" maverick-summary --project "TP-0001" --advance-cursor
```

## Blockers

```powershell
python "scripts\ost_orchestrator.py" maverick-blockers --project "TP-0001"
```

## Failure trends

```powershell
python "scripts\ost_orchestrator.py" maverick-failure-trends --project "TP-0001" --top 10
```

## Quality gates

```powershell
python "scripts\ost_orchestrator.py" maverick-quality-gates --project "TP-0001"
```

## Startup self-check

```powershell
python "scripts\ost_orchestrator.py" maverick-startup-self-check
```

## Daily report

```powershell
python "scripts\ost_orchestrator.py" maverick-daily-report --project "TP-0001" --top 5
```

All-project daily reports:

```powershell
python "scripts\ost_orchestrator.py" maverick-daily-report-all --top 5
```

## Manual step logging

```powershell
python "scripts\ost_orchestrator.py" maverick-log-step --project "TP-0001" --action "boost_run_click" --outcome failure --archetype "boost-run-click" --expected "Run button clicked" --observed "Button not detected" --error "visual anchor mismatch"
```

## Left-blank attempt bridge

```powershell
python "scripts\ost_left_blank_maverick_bridge.py" --project "TP-0001"
```

Reads the latest `left_blank_takeoff_attempt.json` under `output/ost-condition-takeoff/`
and logs stable left-blank gate outcomes into Maverick so blockers/failure trends can
reference the same artifacts.

## Guided click recording (after coach-mode)

```powershell
python "scripts\ost_orchestrator.py" maverick-record-click --project "TP-0001" --archetype "boost-run-click" --x 2211 --y 487 --context "Run button center"
```

## Output artifacts

- `output/maverick/runtime_state.json`
- `output/maverick/runtime_events.jsonl`
- `output/maverick/step_log.jsonl`
- `output/maverick/failures.json`
- `output/maverick/coach_requests.jsonl`
- `output/maverick/click_learning.jsonl`
- `output/maverick/conversations.jsonl`
- `output/maverick/summary_cursor.json`
- `output/maverick/proposed_updates.md`
- `output/maverick/learned_rules.json`
