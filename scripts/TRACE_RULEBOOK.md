# Trace rulebook generator

## Purpose

`trace_rulebook_generator.py` reads an **agent trace** export in **JSON Lines** format (one JSON object per line). Each row should resemble `AgentTraceEvent` in the app: at least `event` (string), plus optional `category`, `result`, `ts`, `id`, `context`.

The script:

- Skips **malformed** lines (invalid JSON, non-object, or missing/blank `event`) and reports how many were skipped.
- Counts **bigrams** and **trigrams** of the `event` field in file order.
- **Prioritizes success-ending chains:** "Top successful patterns" lists n-grams whose **last** event has `result` `success` or legacy `ok` (after normalization, `error` becomes `failure`).
- Surfaces **candidate deterministic replay** chains: every step is one of the event names handled by `replayAgentTraceSequence` in `src/lib/agentTrace.ts` (`tool_selected`, `sheet_selected`, `run_ai_takeoff_started`, `review_approve_all`, `export_paintbrush_csv`), still with a success terminal result and the same frequency threshold.
- Adds **low-confidence / needs-human** content only when the trace is **error-heavy** (about 15% or more of success+failure+cancelled rows are failure or cancelled, and there are at least three such outcomes): then it lists frequent failure/cancel/error-terminal n-grams.

Output is a **draft** markdown rulebook for humans to edit, not an executable policy.

## CLI usage

Required:

- `--input`: path to the `.jsonl` trace file
- `--output`: path for the generated `.md` file

Optional:

- `--min-frequency`: minimum count for an n-gram to appear (default **2**)
- `--max-rules`: maximum lines in the ranked pattern lists (default **50**)

## Example

After exporting trace JSONL (or copying one from CI artifacts), run:

```bash
python3 scripts/trace_rulebook_generator.py \
  --input /opt/cursor/artifacts/agent-trace.jsonl \
  --output /opt/cursor/artifacts/trace-rulebook.md \
  --min-frequency 2 \
  --max-rules 50
```

Adjust the input path to whatever file you have; `/opt/cursor/artifacts` is a typical location for saved trace dumps in some environments.

## How to read the output

- **Summary stats**: row counts, how many lines were skipped, result tallies, and thresholds. Use this to see if the file is big enough for stable patterns.
- **Top successful patterns**: recurring short workflows that **ended in success**. Higher counts suggest repeatable user or agent behavior worth encoding as guidance.
- **Candidate deterministic replay patterns**: subsets that map to known replay hooks. These are stronger candidates for automation **if** context in real traces is complete enough for handlers (the markdown does not prove that).
- **Low-confidence / needs-human**: only when the trace has enough failures/cancellations; lists hot spots before/around bad outcomes. Treat as review queues, not as rules to replay blindly.

N-grams are counted over the **whole file** in order; sessions are **not** split unless you pre-filter the JSONL.
