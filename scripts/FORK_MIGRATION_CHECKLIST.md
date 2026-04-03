# Fork Migration Checklist

Use this when creating the new fork/repo structure.

## Recommended repositories

- `paintbrush-core` (app + UI)
- `paintbrush-ost-agent` (OST black-box automation)
- `paintbrush-intake-intelligence` (intake, scope, reporting)

## Suggested phase-1 split (fast path)

Keep one repo now, but organize by domain folders:

- `scripts/ost_boost_agent.py`
- `scripts/ost_grouping_selector.py`
- `scripts/ost_ui_mapper.py`
- `scripts/ost_project_setup_agent.py`
- `scripts/ost_project_intake.py`
- `scripts/ost_project_scope_report.py`
- `scripts/ost_scope_profiler.py`
- `scripts/ost_training_lab.py`
- `scripts/ost_orchestrator.py`

## Branch strategy

- `main` stable
- `agent-dev` automation changes
- `parity-ui` app parity changes

## Cutover order

1. Confirm mapping is complete (`capture-full`).
2. Run dry-run intake on one project.
3. Enable setup agent and verify one project setup run.
4. Enable watch mode + startup task.
5. Then split repos if desired.
