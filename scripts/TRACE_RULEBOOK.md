# Trace rulebook generator

Turn an exported **agent trace** JSONL file (one JSON object per line, same shape as `AgentTraceEvent` in the app: `event`, `category`, `result`, etc.) into a **markdown rulebook template**. The script counts overlapping **3–6** event windows over **successful** events only (`result` of `success` or legacy `ok`), then emits rules sorted so chains that involve upload, sheet, tool, AI/boost/takeoff, review, or export-style steps appear first.

## Usage

```bash
python3 scripts/trace_rulebook_generator.py \
  --input /path/to/agent-trace.jsonl \
  --output /path/to/rulebook.md
```

Optional:

- `--min-frequency N` — only include subsequences that appear at least **N** times (default **2**).

## Output

Each rule includes:

- **Rule id** — stable short hash from the event chain (`RB-xxxxxxxx`).
- **Frequency** — how often that exact event-name sequence appeared as a sliding window.
- **Event chain** — ordered list of `event` strings.
- **Inferred intent** — one human-readable sentence derived from known event names (heuristic).

This is a drafting aid, not a guaranteed behavioral spec; tune thresholds and edit the markdown after review.
