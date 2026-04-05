# Trace intelligence pipeline (non-UI)

## Purpose

These tools turn an **exported agent trace** (JSON Lines) into artifacts for review and automation planning:

1. **Rulebook** — ranked event n-grams and session-oriented summaries as markdown (human-editable draft guidance).
2. **Replay plan** — a **dry-run** JSON report: which trace rows would map to replay actions and which would be skipped, using the same rules as `replayAgentTraceEvents` in `src/lib/agentReplay.ts` (without registering handlers or touching the app).

This path is **CLI-only**. It does **not** start Vite, Electron, or the server. **`ui:lock:check` / `ui:lock:update` are unchanged** — the UI lock remains a separate concern (`npm run ui:lock:check`, `npm run ui:lock:update`).

## Quick start

From the repo root:

```bash
# Rulebook markdown
npm run trace:rulebook -- --input ./path/to/agent-trace.jsonl --output ./out/trace-rulebook.md

# Replay plan JSON (dry-run)
npm run trace:replay-plan -- --input ./path/to/agent-trace.jsonl --output ./out/trace-replay-plan.json

# Both in one command (default outputs next to the input file)
npm run trace:pipeline -- --input ./path/to/agent-trace.jsonl
```

Override pipeline output paths:

```bash
npm run trace:pipeline -- \
  --input ./path/to/agent-trace.jsonl \
  --rulebook-output ./artifacts/rulebook.md \
  --replay-plan-output ./artifacts/replay-plan.json
```

Show script-specific help:

```bash
npm run trace:rulebook -- --help
npm run trace:replay-plan -- --help
npm run trace:pipeline -- --help
```

## Required input format

- **Format:** JSON Lines (`.jsonl`): one JSON object per line.
- **Minimum per row:** a non-empty string `event`.
- **Recommended fields** (for richer stats and replay checks): `id`, `ts`, `sessionId`, `category`, `result`, `context` — aligned with `AgentTraceEvent` in `src/lib/agentTrace.ts`.
- **Malformed lines** (invalid JSON, non-object, or missing `event`) are skipped; generators print how many lines were skipped where applicable.

For rulebook-specific options (`--min-frequency`, `--by-session`, event filters), see [TRACE_RULEBOOK.md](./TRACE_RULEBOOK.md).

## Outputs produced

| Step | Script | Default / typical output |
|------|--------|-------------------------|
| Rulebook | `trace_rulebook_generator.py` | Markdown: stats, successful n-grams, candidate replay chains, optional per-session sections. |
| Replay plan | `trace_replay_plan_generator.py` | JSON: per-event `applied` / `skipped` with reasons, plus counts (dry-run only). |
| Pipeline | `run_trace_intelligence_pipeline.py` | Runs both; default files `<input-stem>-trace-rulebook.md` and `<input-stem>-trace-replay-plan.json` beside the input unless overridden. |

## Suggested workflow for nightly or autonomous runs

1. **Produce or fetch** a trace JSONL (export from the app, CI artifact, or agent session log).
2. **Run** `npm run trace:pipeline -- --input <file.jsonl>` (or only rulebook / replay-plan if you need one artifact).
3. **Archive** the markdown and JSON next to the input (or upload to your artifact store) with a timestamp or build ID.
4. **Review** the rulebook for recurring workflows; use the replay plan to see how much of the trace is replayable **on paper** before any UI automation.
5. **Keep UI lock separate** — routine builds should still run `npm run ui:lock:check` as today; this pipeline does not replace or modify that.

Optional: schedule the same npm commands in cron, GitHub Actions, or an internal runner; only Python 3 and the repo `scripts/` tree are required (no extra npm dependencies for these steps).
