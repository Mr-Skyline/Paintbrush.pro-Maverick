# OST Orchestrator

Single command entrypoint for intake + setup + training workflows.

## Script

- `scripts/ost_orchestrator.py`

## Common commands

Run one intake pass:

```powershell
python "scripts\ost_orchestrator.py" intake-once --project-filter "10th and Sheridan"
```

Run one intake pass without moving files:

```powershell
python "scripts\ost_orchestrator.py" intake-once --project-filter "10th and Sheridan" --dry-run
```

Watch mode:

```powershell
python "scripts\ost_orchestrator.py" intake-watch
```

Resolve training context:

```powershell
python "scripts\ost_orchestrator.py" discover --project-id "TP-0001"
```

Run boost module:

```powershell
python "scripts\ost_orchestrator.py" run-module --project-id "TP-0001"
```

Run Maverick always-on startup sequence:

```powershell
python "scripts\ost_orchestrator.py" maverick-always-on
```

Chat with Maverick:

```powershell
python "scripts\ost_orchestrator.py" maverick-chat --message "Maverick, what changed since last time?"
```

Get delta summary since last cursor:

```powershell
python "scripts\ost_orchestrator.py" maverick-summary --advance-cursor
```

Show unresolved blockers:

```powershell
python "scripts\ost_orchestrator.py" maverick-blockers
```

Show failure trends:

```powershell
python "scripts\ost_orchestrator.py" maverick-failure-trends --top 10
```

Show quality gates:

```powershell
python "scripts\ost_orchestrator.py" maverick-quality-gates
```

Run startup self-check:

```powershell
python "scripts\ost_orchestrator.py" maverick-startup-self-check
```

Generate daily report:

```powershell
python "scripts\ost_orchestrator.py" maverick-daily-report --top 5
```

Generate daily reports for all tracked projects:

```powershell
python "scripts\ost_orchestrator.py" maverick-daily-report-all --top 5
```

Log step outcomes from external automation:

```powershell
python "scripts\ost_orchestrator.py" maverick-log-step --project "TP-0001" --action "boost_run_click" --outcome failure --archetype "boost-run-click" --expected "Run button clicked" --observed "Button not detected" --error "visual anchor mismatch"
```

Record guided click after coaching:

```powershell
python "scripts\ost_orchestrator.py" maverick-record-click --project "TP-0001" --archetype "boost-run-click" --x 2211 --y 487 --context "Run button center"
```

Full cycle (intake then module):

```powershell
python "scripts\ost_orchestrator.py" full-cycle --project-filter "10th and Sheridan" --run-boost-module --project-id "TP-0001"
```

## Windows startup task

Install auto-start Maverick runtime task:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts\install_ost_intake_watch_task.ps1"
```

Install legacy intake-only mode (optional):

```powershell
powershell -ExecutionPolicy Bypass -File "scripts\install_ost_intake_watch_task.ps1" -Mode intake-watch -TaskName "PaintbrushOSTIntakeWatch"
```

Remove task:

```powershell
powershell -ExecutionPolicy Bypass -File "scripts\uninstall_ost_intake_watch_task.ps1"
```
