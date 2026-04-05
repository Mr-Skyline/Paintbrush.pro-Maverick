# Trace rulebook generator

## Purpose

`trace_rulebook_generator.py` reads an **agent trace** export in **JSON Lines** format (one JSON object per line). Each row should resemble `AgentTraceEvent` in the app: at least `event` (string), plus optional `category`, `result`, `ts`, `id`, `sessionId`, `context`.

The script:

- Skips **malformed** lines (invalid JSON, non-object, or missing/blank `event`) and reports how many were skipped.
- Optionally keeps only rows whose `event` is in `--include-events`, or drops rows in `--exclude-events`, before any counting or n-gram mining.
- Counts **bigrams** and **trigrams** of the `event` field in file order (after event filters).
- **Prioritizes success-ending chains:** "Top successful patterns" lists n-grams whose **last** event has `result` `success` or legacy `ok` (after normalization, `error` becomes `failure`).
- Surfaces **candidate deterministic replay** chains: every step is one of the event names handled by `replayAgentTraceSequence` in `src/lib/agentTrace.ts` (`tool_selected`, `sheet_selected`, `run_ai_takeoff_started`, `review_approve_all`, `export_paintbrush_csv`), still with a success terminal result and the same frequency threshold.
- Adds **low-confidence / needs-human** content only when the trace is **error-heavy** (about 15% or more of success+failure+cancelled rows are failure or cancelled, and there are at least three such outcomes): then it lists frequent failure/cancel/error-terminal n-grams.
- With `--by-session`, emits a **Per-session breakdown** first: for each distinct non-empty `sessionId` (in first-seen order), a short summary plus the same three pattern sections for that session only. **Global** sections still aggregate all rows after event filters.

Output is a **draft** markdown rulebook for humans to edit, not an executable policy.

## CLI usage

Required:

- `--input`: path to the `.jsonl` trace file
- `--output`: path for the generated `.md` file

Optional:

- `--min-frequency`: minimum count for an n-gram to appear (default **2**)
- `--max-rules`: maximum lines in the ranked pattern lists (default **50**)
- `--by-session`: split pattern mining per `sessionId` (when present) and add per-session sections before the global summary; global output still includes all filtered rows
- `--include-events`: comma-separated `event` names; only those rows are used for stats and n-grams (others dropped)
- `--exclude-events`: comma-separated `event` names to drop before stats and n-grams

If every row lacks a non-empty `sessionId`, `--by-session` adds a short note and does not duplicate per-session pattern blocks (global sections only).

## Examples

After exporting trace JSONL (or copying one from CI artifacts), run:

```bash
python3 scripts/trace_rulebook_generator.py \
  --input /opt/cursor/artifacts/agent-trace.jsonl \
  --output /opt/cursor/artifacts/trace-rulebook.md \
  --min-frequency 2 \
  --max-rules 50
```

Per-session sections plus global aggregate:

```bash
python3 scripts/trace_rulebook_generator.py \
  --input /opt/cursor/artifacts/agent-trace.jsonl \
  --output /opt/cursor/artifacts/trace-rulebook-by-session.md \
  --by-session
```

Only replay-related events (mining and tallies use this subset):

```bash
python3 scripts/trace_rulebook_generator.py \
  --input /opt/cursor/artifacts/agent-trace.jsonl \
  --output /opt/cursor/artifacts/trace-rulebook-replay.md \
  --include-events tool_selected,sheet_selected,run_ai_takeoff_started,review_approve_all,export_paintbrush_csv
```

Drop noisy events from the analysis:

```bash
python3 scripts/trace_rulebook_generator.py \
  --input /opt/cursor/artifacts/agent-trace.jsonl \
  --output /opt/cursor/artifacts/trace-rulebook-filtered.md \
  --exclude-events heartbeat,debug_ping
```

Adjust the input path to whatever file you have; `/opt/cursor/artifacts` is a typical location for saved trace dumps in some environments.

## How to read the output

- **Per-session breakdown** (when `--by-session` and rows have `sessionId`): per-session **Summary** bullets, then the same pattern sections scoped to that session. Use this to compare workflows across sessions without pre-splitting the file.
- **Summary stats**: total valid rows in the file, rows after event filters, how many lines were malformed, result tallies (after filters), and thresholds. Use this to see if the file is big enough for stable patterns.
- **Top successful patterns**: recurring short workflows that **ended in success**. Higher counts suggest repeatable user or agent behavior worth encoding as guidance.
- **Candidate deterministic replay patterns**: subsets that map to known replay hooks. These are stronger candidates for automation **if** context in real traces is complete enough for handlers (the markdown does not prove that).
- **Low-confidence / needs-human**: only when the trace has enough failures/cancellations; lists hot spots before/around bad outcomes. Treat as review queues, not as rules to replay blindly.

N-grams in the **global** sections are counted over **all** filtered rows in file order. With `--by-session`, per-session sections use only that session’s rows (same ordering as in the file).
