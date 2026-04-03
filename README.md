# Paintbrush Takeoff (OST-style)

React 18 + Vite + TypeScript + Tailwind + Zustand · **pdf.js** · **Fabric.js** · **Socket.IO** · IndexedDB + optional **File System Access API** (Chrome/Edge) · ElevenLabs + Grok (server).

## Run (dev)

From the project folder:

```powershell
cd "C:\Users\travi\OneDrive\Documents\Paintbrush.pro"
npm install
npm run dev
```

- Vite: **http://localhost:5173**
- API / Socket.IO: **http://localhost:3000** (proxied from Vite)

## Desktop App (Electron)

Run a clean desktop UI for invoice review:

```powershell
cd "C:\Users\travi\OneDrive\Documents\Paintbrush.pro"
npm install
npm run dev:desktop
```

Production-style desktop launch:

```powershell
npm run desktop
```

Desktop UI includes:
- native file picker for invoice files (`PDF/JPG/JPEG/PNG/WEBP/TIF/TIFF`)
- native file picker for product database JSON
- one-click invoice review run
- summary cards + run log
- quick-open buttons for grouped JSON, flagged PDF, and flagged XLSX reports
- automatic opening of generated PDF + XLSX reports after each completed review run
- unmatched product queue with actions to:
  - add unknown item as a new product
  - assign unknown item token to an existing product alias
- editable product database grid (SKU/name/unit price/aliases) with explicit save approval prompt
- if no database is selected (or file is missing), app prompts to create a new JSON DB and writes the correct format automatically
- auto-save option keeps DB file updated as you edit products in the UI

## Flow

1. **Projects** — saved jobs from IndexedDB; **Link workspace folder** picks a disk root (handle stored in IndexedDB).
2. **New project** — multi-PDF drop/browse; PDFs stored as `ost-pdf:{projectId}:{docId}`; state in `project.ost.json` equivalent (`ost-json:{projectId}`).
3. **Workspace** — plan set switcher in left sidebar; marks keyed by `{documentId}:{page}`; **Save** / **auto-save every 30s** to IndexedDB; **Sync disk** writes `{root}/{projectId}/project.ost.json` + `pdfs/`; **Paintbrush CSV** + optional `exports/` CSV; **Zip** downloads `projects/{id}/...` layout via JSZip.

## Env (server)

See `.env.example`: `ELEVENLABS_*`, `GROK_API_KEY` (xAI).

Voice uses **`POST /api/agent/step`**: Grok receives tools (`boost_run`, `boost_apply_review`, conditions, canvas, save, etc.); the browser executes tool results in a loop until the model replies in plain text. Requires a model/key that supports OpenAI-style function calling on the xAI API.

## Telegram Field Estimator Bot

Create a Telegram bot with [@BotFather](https://t.me/BotFather), then set:

- `TELEGRAM_BOT_TOKEN`
- `GROK_API_KEY` (optional but recommended for a polished report narrative)
- Optional tuning:
  - `PAINT_COVERAGE_SQFT_PER_GALLON` (default `350`)
  - `DEFAULT_PAINT_COATS` (default `2`)

The bot also supports your existing local key files as fallback:

- `telegram.txt` for the bot token
- `builderbot grok api.txt` for the Grok key
- `.env.txt` key/value format (same style as `.env`)

Run:

```powershell
npm run bot:telegram
```

### Telegram workflow

- Send field notes and measurements as plain text while walking the job.
- Include either dimensions (`12 x 8`) or area (`180 sqft`) to auto-log measurements.
- Use `/status` anytime for running totals.
- Send `/done` when the walkthrough is complete to generate a review report.
- Send `/new` to start the next property session.

## Watch folder

Browsers cannot watch arbitrary paths. Stub: `node scripts/watch-incoming.mjs "C:\path"` — extend with `chokidar` + your integration.

## Invoice Price Review Utility

Reviews material invoices (`PDF`, `JPG`, `JPEG`, `PNG`, `WEBP`, `TIF/TIFF`) and compares invoice prices against a local product-price database.

### 1) Prepare database file

Use `scripts/invoice-product-prices.example.json` as a template:

```json
[
  {
    "sku": "LMBR-2X4X8",
    "name": "Lumber 2x4x8",
    "unitPrice": 4.99,
    "aliases": ["2x4x8 lumber", "stud 2x4 8"]
  }
]
```

### 2) Place invoices in a folder

Example: `C:\Users\travi\OneDrive\Documents\Paintbrush.pro\invoices`

### 3) Run review

```powershell
npm run invoice:review -- --invoices "./invoices" --db "./scripts/invoice-product-prices.example.json" --out "./output/invoice-review"
```

Optional:
- `--tolerance 0.01` allows tiny rounding differences before flagging
- `--files "C:\path\invoice1.pdf" --files "C:\path\invoice2.jpg"` processes specific files instead of scanning a folder
- `--extract-only` parses project/PO and item rows without doing DB price comparison

### 4) Outputs

The tool writes:
- `output/invoice-review/invoice-review-results.json` (per-invoice raw findings)
- `output/invoice-review/flagged-by-project-or-po.json` (grouped by project/PO)
- `output/invoice-review/candidate-product-prices.json` (deduplicated SKU/price seed list from parsed invoice rows)
- `output/invoice-review/flagged-items-by-project-or-po.pdf` (professional PDF report)
- `output/invoice-review/flagged-items-by-project-or-po.xlsx` (professional Excel report)

Notes:
- Project and PO are extracted with text pattern matching (`Project:`, `Job:`, `PO#`, etc.).
- Scanned/image-based invoices use OCR (`tesseract.js`).
- Very inconsistent invoice layouts may need you to improve aliases in the product DB for better matching.
- In `--extract-only` mode, PDF report generation is skipped and JSON outputs are still generated for parser tuning.

## Legacy

Old static files under `public/` are unused by the React app.
