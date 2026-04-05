import { useEffect, useMemo, useState } from 'react';

type ReviewResult = {
  ok: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
};

type ParsedItem = {
  sku?: string;
  quantity?: number | null;
  observedPrice?: number;
  sourceLine?: string;
};

type InvoiceResult = {
  file: string;
  project: string;
  po: string;
  parsedItems?: ParsedItem[];
};

function StatCard({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-2xl border border-slate-700/60 bg-slate-900/60 p-4 shadow-[0_12px_35px_rgba(0,0,0,0.35)]">
      <div className="text-xs uppercase tracking-[0.18em] text-slate-400">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
    </div>
  );
}

export function DesktopInvoiceScreen() {
  const desktop = window.desktopApi ?? null;
  const [takeoffInputPath, setTakeoffInputPath] = useState('');
  const [takeoffOutputDir, setTakeoffOutputDir] = useState('');
  const [takeoffProjectId, setTakeoffProjectId] = useState('');
  const [takeoffConfigPath, setTakeoffConfigPath] = useState('');
  const [takeoffSaveOverlays, setTakeoffSaveOverlays] = useState(true);
  const [takeoffSaveDebug, setTakeoffSaveDebug] = useState(false);
  const [takeoffSupabase, setTakeoffSupabase] = useState(false);
  const [takeoffRunning, setTakeoffRunning] = useState(false);
  const [takeoffResult, setTakeoffResult] =
    useState<DesktopTakeoffRunResult | null>(null);
  const [files, setFiles] = useState<string[]>([]);
  const [dbPath, setDbPath] = useState('');
  const [dbProducts, setDbProducts] = useState<DesktopProductRecord[]>([]);
  const [dbDirty, setDbDirty] = useState(false);
  const [autoSaveDb, setAutoSaveDb] = useState(true);
  const [autoSavingDb, setAutoSavingDb] = useState(false);
  const [outDir, setOutDir] = useState('');
  const [tolerance, setTolerance] = useState('0.01');
  const [extractOnly, setExtractOnly] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<ReviewResult | null>(null);
  const [summary, setSummary] = useState<{
    scannedInvoices?: number;
    flaggedGroups?: number;
    totalFlaggedItems?: number;
    extractOnly?: boolean;
  } | null>(null);
  const [invoiceRows, setInvoiceRows] = useState<InvoiceResult[]>([]);
  const [dbStatus, setDbStatus] = useState('');
  const [selectedProductByUnmatched, setSelectedProductByUnmatched] = useState<
    Record<string, string>
  >({});
  const [resultPaths, setResultPaths] = useState<{
    raw?: string;
    grouped?: string;
    candidateDb?: string;
    pdf?: string;
    xlsx?: string;
  } | null>(null);

  const canRun = useMemo(() => {
    return Boolean(desktop);
  }, [desktop]);

  const unmatchedItems = useMemo(() => {
    const knownSkus = new Set(dbProducts.map((p) => p.sku.trim().toLowerCase()));
    const unmatched = new Map<
      string,
      { token: string; observedPrice: number; invoiceFile: string; sourceLine: string }
    >();

    for (const invoice of invoiceRows) {
      for (const item of invoice.parsedItems || []) {
        const token = String(item.sku || '').trim();
        if (!token) continue;
        const key = token.toLowerCase();
        if (knownSkus.has(key)) continue;
        if (!unmatched.has(key)) {
          unmatched.set(key, {
            token,
            observedPrice: Number(item.observedPrice || 0),
            invoiceFile: invoice.file,
            sourceLine: String(item.sourceLine || ''),
          });
        }
      }
    }
    return Array.from(unmatched.values()).sort((a, b) =>
      a.token.localeCompare(b.token)
    );
  }, [dbProducts, invoiceRows]);

  const pickFiles = async () => {
    if (!desktop) return;
    const selected = await desktop.pickInvoiceFiles();
    if (Array.isArray(selected) && selected.length) setFiles(selected);
  };

  const loadDatabase = async (path: string) => {
    if (!desktop || !path.trim()) return;
    const result = await desktop.readDb(path);
    if (!result.ok) {
      setDbStatus(result.error || 'Failed to load database.');
      return;
    }
    setDbProducts(result.products || []);
    setDbDirty(false);
    setDbStatus(`Loaded ${result.products?.length || 0} products.`);
  };

  const pickDbFile = async () => {
    if (!desktop) return;
    const selected = await desktop.pickDbFile();
    if (selected) {
      setDbPath(selected);
      await loadDatabase(selected);
    }
  };

  const pickOutDir = async () => {
    if (!desktop) return;
    const selected = await desktop.pickOutputDirectory();
    if (selected) setOutDir(selected);
  };

  const ensureDatabaseReady = async (): Promise<string | null> => {
    if (extractOnly) return '';
    if (!desktop) return null;

    let targetPath = dbPath.trim();
    if (!targetPath) {
      const approved = window.confirm(
        'No product database is selected.\n\nCreate a new database file now?'
      );
      if (!approved) {
        setDbStatus('Database selection required for comparison mode.');
        return null;
      }
      if (!desktop.pickDbCreatePath || !desktop.createDb) {
        setDbStatus(
          'Database creation API unavailable. Restart the desktop app to load latest features.'
        );
        return null;
      }
      const newPath = await desktop.pickDbCreatePath();
      if (!newPath) {
        setDbStatus('Database creation cancelled.');
        return null;
      }
      const created = await desktop.createDb(newPath, []);
      if (!created.ok) {
        setDbStatus(created.error || 'Could not create database file.');
        return null;
      }
      setDbPath(newPath);
      setDbProducts(created.products || []);
      setDbDirty(false);
      setDbStatus(`Created database at ${newPath}.`);
      return newPath;
    }

    const read = await desktop.readDb(targetPath);
    if (read.ok) return targetPath;

    const approved = window.confirm(
      `Selected database could not be loaded.\n\n${read.error || 'Unknown error'}\n\nCreate a new database file at this path?`
    );
    if (!approved) {
      setDbStatus('Database could not be loaded; review cancelled.');
      return null;
    }
    if (!desktop.createDb) {
      setDbStatus(
        'Database creation API unavailable. Restart the desktop app to load latest features.'
      );
      return null;
    }
    const created = await desktop.createDb(targetPath, []);
    if (!created.ok) {
      setDbStatus(created.error || 'Could not create database file.');
      return null;
    }
    setDbProducts(created.products || []);
    setDbDirty(false);
    setDbStatus(`Created database at ${targetPath}.`);
    return targetPath;
  };

  const runReview = async () => {
    if (!desktop) {
      setDbStatus('Desktop API unavailable. Restart app with npm run dev:desktop.');
      return;
    }

    try {
      let activeFiles = files;
      if (!activeFiles.length) {
        const selected = await desktop.pickInvoiceFiles();
        if (!Array.isArray(selected) || selected.length === 0) {
          setDbStatus('No invoice files selected.');
          return;
        }
        setFiles(selected);
        activeFiles = selected;
      }

      let activeOutDir = outDir.trim();
      if (!activeOutDir) {
        const selectedOutDir = await desktop.pickOutputDirectory();
        if (!selectedOutDir) {
          setDbStatus('No output folder selected.');
          return;
        }
        setOutDir(selectedOutDir);
        activeOutDir = selectedOutDir;
      }

      const readyDbPath = await ensureDatabaseReady();
      if (readyDbPath === null) return;

      setRunning(true);
      setRunResult(null);
      setSummary(null);

      const response = (await desktop.runReview({
        files: activeFiles,
        dbPath: extractOnly ? '' : readyDbPath,
        outDir: activeOutDir,
        tolerance: Number(tolerance),
        extractOnly,
      })) as ReviewResult;
      setRunResult(response);
      const data = (await desktop.getResults(activeOutDir)) as {
        raw: InvoiceResult[] | null;
        grouped:
          | {
              summary?: {
                scannedInvoices?: number;
                flaggedGroups?: number;
                totalFlaggedItems?: number;
                extractOnly?: boolean;
              };
            }
          | null;
        files: {
          raw: string;
          grouped: string;
          candidateDb: string;
          pdf: string;
          xlsx: string;
        };
      };
      setInvoiceRows(Array.isArray(data.raw) ? data.raw : []);
      setSummary(data.grouped?.summary || null);
      setResultPaths(data.files || null);
      if (!extractOnly) {
        const openedPdf = data.files.pdf ? await desktop.openPath(data.files.pdf) : false;
        const openedXlsx = data.files.xlsx
          ? await desktop.openPath(data.files.xlsx)
          : false;
        if (!openedPdf || !openedXlsx) {
          await desktop.openPath(activeOutDir);
          setDbStatus(
            'Report generated. Some files could not auto-open directly, so output folder was opened.'
          );
          return;
        }
      }
      setDbStatus('Invoice review completed.');
    } catch (error) {
      setDbStatus(
        `Run failed: ${error instanceof Error ? error.message : String(error)}`
      );
    } finally {
      setRunning(false);
    }
  };

  const pickTakeoffInput = async () => {
    if (!desktop?.pickTakeoffInput) return;
    const selected = await desktop.pickTakeoffInput();
    if (selected) setTakeoffInputPath(selected);
  };

  const pickTakeoffOutput = async () => {
    if (!desktop?.pickTakeoffOutputDirectory) return;
    const selected = await desktop.pickTakeoffOutputDirectory();
    if (selected) setTakeoffOutputDir(selected);
  };

  const runTakeoffAgent = async () => {
    if (!desktop?.runTakeoffAgent) return;
    if (!takeoffInputPath.trim()) {
      setDbStatus('Takeoff input file is required.');
      return;
    }
    if (!takeoffOutputDir.trim()) {
      setDbStatus('Takeoff output folder is required.');
      return;
    }
    setTakeoffRunning(true);
    setTakeoffResult(null);
    try {
      const response = await desktop.runTakeoffAgent({
        input: takeoffInputPath.trim(),
        outDir: takeoffOutputDir.trim(),
        projectId: takeoffProjectId.trim() || undefined,
        configPath: takeoffConfigPath.trim() || undefined,
        saveOverlays: takeoffSaveOverlays,
        saveDebugImages: takeoffSaveDebug,
        enableSupabaseHandoff: takeoffSupabase,
      });
      setTakeoffResult(response);
      if (response.ok) {
        setDbStatus('Takeoff agent run completed.');
      } else {
        setDbStatus(`Takeoff agent failed (exit ${response.exitCode}).`);
      }
    } catch (error) {
      setDbStatus(
        `Takeoff run failed: ${error instanceof Error ? error.message : String(error)}`
      );
    } finally {
      setTakeoffRunning(false);
    }
  };

  const updateProduct = (
    index: number,
    field: 'sku' | 'name' | 'unitPrice' | 'aliases',
    value: string
  ) => {
    setDbDirty(true);
    setDbProducts((current) =>
      current.map((row, i) => {
        if (i !== index) return row;
        if (field === 'aliases') {
          return {
            ...row,
            aliases: value
              .split(',')
              .map((alias) => alias.trim())
              .filter(Boolean),
          };
        }
        if (field === 'unitPrice') {
          return {
            ...row,
            unitPrice: Number(value),
          };
        }
        return { ...row, [field]: value };
      })
    );
  };

  const saveDb = async () => {
    if (!desktop || !dbPath.trim()) return;
    const result = await desktop.writeDb(dbPath, dbProducts);
    if (result.ok) {
      setDbStatus(`Saved ${dbProducts.length} products.`);
      setDbDirty(false);
      if (result.products) setDbProducts(result.products);
      return;
    }
    setDbStatus(result.cancelled ? 'Save cancelled.' : result.error || 'Save failed.');
  };

  const addUnmatchedAsProduct = (token: string, observedPrice: number) => {
    const approved = window.confirm(
      `Add "${token}" as a NEW product?\n\n` +
        `Default name: ${token}\n` +
        `Default unit price: ${observedPrice.toFixed(2)}\n\n` +
        'This will update the in-app database and auto-save to disk.'
    );
    if (!approved) {
      setDbStatus(`Add cancelled for ${token}.`);
      return;
    }

    setDbProducts((current) => {
      if (current.some((p) => p.sku.trim().toLowerCase() === token.toLowerCase())) {
        return current;
      }
      return [
        ...current,
        {
          sku: token,
          name: token,
          unitPrice: Number.isFinite(observedPrice) ? observedPrice : 0,
          aliases: [],
        },
      ];
    });
    setDbDirty(true);
    setDbStatus(`Added ${token} to database editor.`);
  };

  const assignUnmatchedToProduct = (token: string) => {
    const targetSku = selectedProductByUnmatched[token];
    if (!targetSku) {
      setDbStatus(`Select a target product before assigning ${token}.`);
      return;
    }

    const targetProduct = dbProducts.find((product) => product.sku === targetSku);
    const approved = window.confirm(
      `Assign "${token}" to existing product "${targetSku}"` +
        `${targetProduct?.name ? ` (${targetProduct.name})` : ''} as an alias?\n\n` +
        'This will improve matching for future invoices.\n\n' +
        'This will update the in-app database and auto-save to disk.'
    );
    if (!approved) {
      setDbStatus(`Alias assignment cancelled for ${token}.`);
      return;
    }

    setDbProducts((current) =>
      current.map((product) => {
        if (product.sku !== targetSku) return product;
        if (product.aliases.includes(token)) return product;
        return { ...product, aliases: [...product.aliases, token] };
      })
    );
    setDbDirty(true);
    setDbStatus(`Assigned "${token}" as alias to ${targetSku}.`);
  };

  useEffect(() => {
    if (!desktop || !autoSaveDb || !dbDirty || !dbPath.trim()) return;
    const timer = window.setTimeout(async () => {
      setAutoSavingDb(true);
      const result = await desktop.writeDbAuto(dbPath, dbProducts);
      setAutoSavingDb(false);
      if (result.ok) {
        setDbDirty(false);
        setDbStatus(`Auto-saved ${dbProducts.length} products.`);
      } else {
        setDbStatus(result.error || 'Auto-save failed.');
      }
    }, 700);
    return () => window.clearTimeout(timer);
  }, [autoSaveDb, dbDirty, dbPath, dbProducts, desktop]);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_0%_0%,#1e3a8a_0%,#0b1020_35%,#04070f_100%)] px-8 py-10 text-slate-100">
      <div className="mx-auto max-w-7xl">
        <header className="mb-8">
          <p className="text-xs uppercase tracking-[0.22em] text-cyan-300/80">
            Skyline Invoice Intelligence
          </p>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight text-white">
            Desktop Invoice Review
          </h1>
          <p className="mt-3 max-w-3xl text-sm text-slate-300/90">
            Review PDF/image invoices, compare prices against your local product
            database, and export flagged items grouped by project or PO.
          </p>
        </header>

        {!desktop && (
          <div className="mb-8 rounded-2xl border border-amber-500/50 bg-amber-500/10 p-4 text-amber-100">
            Desktop API unavailable. Launch this as an Electron app using
            <span className="ml-1 rounded bg-black/30 px-2 py-0.5 font-mono text-xs">
              npm run dev:desktop
            </span>
            .
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[1.2fr,0.8fr]">
          <section className="rounded-3xl border border-slate-700/60 bg-slate-900/70 p-6 shadow-[0_18px_60px_rgba(7,10,22,0.45)] backdrop-blur">
            <h2 className="text-lg font-semibold text-white">Inputs</h2>
            <div className="mt-5 space-y-4">
              <div className="rounded-xl border border-slate-700/70 bg-black/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-white">
                      Invoice files
                    </div>
                    <div className="text-xs text-slate-400">
                      PDF, JPG, JPEG, PNG, WEBP, TIF, TIFF
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={pickFiles}
                    className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-semibold text-slate-950 hover:bg-cyan-400"
                  >
                    Choose files
                  </button>
                </div>
                <div className="mt-3 max-h-40 space-y-1 overflow-auto rounded-lg bg-slate-950/70 p-2 text-xs">
                  {files.length ? (
                    files.map((file) => (
                      <div key={file} className="truncate text-slate-200">
                        {file}
                      </div>
                    ))
                  ) : (
                    <div className="text-slate-500">No invoice files selected.</div>
                  )}
                </div>
              </div>

              <div className="rounded-xl border border-slate-700/70 bg-black/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium text-white">
                    Product price database (JSON)
                  </div>
                  <button
                    type="button"
                    onClick={pickDbFile}
                    className="rounded-lg border border-slate-600 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                    disabled={extractOnly}
                  >
                    Select DB
                  </button>
                </div>
                <div className="mt-2 truncate rounded-lg bg-slate-950/70 px-3 py-2 text-xs text-slate-300">
                  {extractOnly
                    ? 'Not required in extract-only mode.'
                    : dbPath || 'No database file selected.'}
                </div>
                {dbPath && (
                  <button
                    type="button"
                    onClick={() => void loadDatabase(dbPath)}
                    className="mt-3 rounded-lg border border-cyan-500/60 px-3 py-2 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/10"
                  >
                    Reload DB into editor
                  </button>
                )}
              </div>

              <div className="rounded-xl border border-slate-700/70 bg-black/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium text-white">
                    Output directory
                  </div>
                  <button
                    type="button"
                    onClick={pickOutDir}
                    className="rounded-lg border border-slate-600 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    Select folder
                  </button>
                </div>
                <div className="mt-2 truncate rounded-lg bg-slate-950/70 px-3 py-2 text-xs text-slate-300">
                  {outDir || 'No output folder selected.'}
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="rounded-xl border border-slate-700/70 bg-black/20 p-4 text-sm">
                  <div className="mb-2 font-medium text-white">Tolerance</div>
                  <input
                    value={tolerance}
                    onChange={(e) => setTolerance(e.target.value)}
                    className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white focus:border-cyan-400 focus:outline-none"
                  />
                </label>
                <label className="flex items-center gap-3 rounded-xl border border-slate-700/70 bg-black/20 p-4 text-sm">
                  <input
                    type="checkbox"
                    checked={extractOnly}
                    onChange={(e) => setExtractOnly(e.target.checked)}
                    className="h-4 w-4 rounded border-slate-500 bg-slate-950 text-cyan-400"
                  />
                  <span>
                    <div className="font-medium text-white">Extract-only mode</div>
                    <div className="text-xs text-slate-400">
                      Parse metadata/items without DB mismatch checks.
                    </div>
                  </span>
                </label>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={runReview}
                disabled={!canRun || running}
                className="rounded-xl bg-emerald-400 px-5 py-3 text-sm font-semibold text-slate-950 shadow-[0_12px_24px_rgba(16,185,129,0.35)] transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-300"
              >
                {running ? 'Reviewing invoices...' : 'Run invoice review'}
              </button>
              {resultPaths?.pdf && !extractOnly && (
                <button
                  type="button"
                  onClick={() => void desktop?.openPath(resultPaths.pdf!)}
                  className="rounded-xl border border-cyan-400/50 px-4 py-3 text-sm text-cyan-200 hover:bg-cyan-400/10"
                >
                  Open flagged PDF report
                </button>
              )}
              {resultPaths?.xlsx && !extractOnly && (
                <button
                  type="button"
                  onClick={() => void desktop?.openPath(resultPaths.xlsx!)}
                  className="rounded-xl border border-cyan-400/50 px-4 py-3 text-sm text-cyan-200 hover:bg-cyan-400/10"
                >
                  Open flagged XLSX report
                </button>
              )}
              {resultPaths?.grouped && (
                <button
                  type="button"
                  onClick={() => void desktop?.openPath(resultPaths.grouped!)}
                  className="rounded-xl border border-slate-500 px-4 py-3 text-sm text-slate-200 hover:bg-slate-800/60"
                >
                  Open grouped JSON
                </button>
              )}
            </div>
          </section>

          <section className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-3">
              <StatCard
                label="Invoices Scanned"
                value={summary?.scannedInvoices ?? '-'}
              />
              <StatCard
                label="Flagged Groups"
                value={summary?.flaggedGroups ?? '-'}
              />
              <StatCard
                label="Flagged Items"
                value={summary?.totalFlaggedItems ?? '-'}
              />
            </div>

            <div className="rounded-3xl border border-slate-700/60 bg-slate-900/70 p-6 shadow-[0_18px_60px_rgba(7,10,22,0.45)]">
              <h2 className="text-lg font-semibold text-white">Run Log</h2>
              <pre className="mt-4 max-h-[440px] overflow-auto rounded-xl bg-slate-950/90 p-4 text-xs leading-5 text-emerald-200">
                {runResult
                  ? `${runResult.stdout}${runResult.stderr ? `\n${runResult.stderr}` : ''}`
                  : 'No run yet.'}
              </pre>
              {runResult && !runResult.ok && (
                <p className="mt-3 text-sm text-rose-300">
                  Run failed with exit code {runResult.exitCode}. Check log.
                </p>
              )}
            </div>
          </section>
        </div>

        <section className="mt-6 grid gap-6 lg:grid-cols-2">
          <div className="rounded-3xl border border-slate-700/60 bg-slate-900/70 p-6 shadow-[0_18px_60px_rgba(7,10,22,0.45)] lg:col-span-2">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Takeoff Agent Runner</h2>
              <button
                type="button"
                onClick={runTakeoffAgent}
                disabled={!desktop || takeoffRunning}
                className="rounded-xl bg-emerald-400 px-4 py-2 text-sm font-semibold text-slate-950 shadow-[0_12px_24px_rgba(16,185,129,0.35)] hover:bg-emerald-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-300"
              >
                {takeoffRunning ? 'Running...' : 'Run Takeoff Agent'}
              </button>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-slate-700/70 bg-black/20 p-4">
                <div className="text-sm font-medium text-white">
                  Blueprint input (PDF/image)
                </div>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    onClick={pickTakeoffInput}
                    className="rounded-lg border border-slate-600 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    Select file
                  </button>
                  <input
                    value={takeoffInputPath}
                    onChange={(e) => setTakeoffInputPath(e.target.value)}
                    placeholder="/abs/path/to/plan.pdf"
                    className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-xs text-white"
                  />
                </div>
              </div>
              <div className="rounded-xl border border-slate-700/70 bg-black/20 p-4">
                <div className="text-sm font-medium text-white">Output folder</div>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    onClick={pickTakeoffOutput}
                    className="rounded-lg border border-slate-600 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    Select folder
                  </button>
                  <input
                    value={takeoffOutputDir}
                    onChange={(e) => setTakeoffOutputDir(e.target.value)}
                    placeholder="/abs/path/to/output"
                    className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-xs text-white"
                  />
                </div>
              </div>
              <label className="rounded-xl border border-slate-700/70 bg-black/20 p-4 text-sm">
                <div className="mb-2 font-medium text-white">Project ID (optional)</div>
                <input
                  value={takeoffProjectId}
                  onChange={(e) => setTakeoffProjectId(e.target.value)}
                  placeholder="my-project-id"
                  className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-xs text-white"
                />
              </label>
              <label className="rounded-xl border border-slate-700/70 bg-black/20 p-4 text-sm">
                <div className="mb-2 font-medium text-white">Config path (optional)</div>
                <input
                  value={takeoffConfigPath}
                  onChange={(e) => setTakeoffConfigPath(e.target.value)}
                  placeholder="/workspace/takeoff_agent/config.yaml"
                  className="w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-xs text-white"
                />
              </label>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-slate-300">
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={takeoffSaveOverlays}
                  onChange={(e) => setTakeoffSaveOverlays(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-500 bg-slate-950 text-cyan-400"
                />
                Save overlays
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={takeoffSaveDebug}
                  onChange={(e) => setTakeoffSaveDebug(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-500 bg-slate-950 text-cyan-400"
                />
                Save debug images
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={takeoffSupabase}
                  onChange={(e) => setTakeoffSupabase(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-500 bg-slate-950 text-cyan-400"
                />
                Enable Supabase handoff
              </label>
            </div>
            <pre className="mt-4 max-h-64 overflow-auto rounded-xl bg-slate-950/90 p-4 text-xs leading-5 text-emerald-200">
              {takeoffResult
                ? `${takeoffResult.stdout}${takeoffResult.stderr ? `\n${takeoffResult.stderr}` : ''}`
                : 'No takeoff run yet.'}
            </pre>
          </div>

          <div className="rounded-3xl border border-slate-700/60 bg-slate-900/70 p-6 shadow-[0_18px_60px_rgba(7,10,22,0.45)]">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">
                Unmatched Products ({unmatchedItems.length})
              </h2>
              <button
                type="button"
                onClick={() => {
                  setDbProducts((current) => [
                    ...current,
                    { sku: '', name: '', unitPrice: 0, aliases: [] },
                  ]);
                  setDbDirty(true);
                  setDbStatus('Added blank product row.');
                }}
                className="rounded-lg border border-slate-600 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800"
              >
                Add blank product
              </button>
            </div>
            <div className="max-h-[380px] space-y-3 overflow-auto pr-1">
              {unmatchedItems.length === 0 ? (
                <div className="rounded-xl border border-slate-700/70 bg-slate-950/70 p-4 text-sm text-slate-400">
                  No unmatched SKU tokens from the latest run.
                </div>
              ) : (
                unmatchedItems.map((item) => (
                  <div
                    key={item.token}
                    className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4"
                  >
                    <div className="text-sm font-semibold text-amber-100">
                      {item.token}
                    </div>
                    <div className="mt-1 text-xs text-amber-200/80">
                      Sample invoice price: {item.observedPrice.toFixed(2)}
                    </div>
                    <div className="truncate text-xs text-slate-300/90">
                      {item.invoiceFile}
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          addUnmatchedAsProduct(item.token, item.observedPrice)
                        }
                        className="rounded-lg bg-emerald-400 px-3 py-2 text-xs font-semibold text-slate-950 hover:bg-emerald-300"
                      >
                        Add as new product
                      </button>
                      <select
                        value={selectedProductByUnmatched[item.token] || ''}
                        onChange={(e) =>
                          setSelectedProductByUnmatched((current) => ({
                            ...current,
                            [item.token]: e.target.value,
                          }))
                        }
                        className="min-w-[180px] rounded-lg border border-slate-600 bg-slate-950 px-2 py-2 text-xs text-white"
                      >
                        <option value="">Assign to existing product...</option>
                        {dbProducts.map((product) => (
                          <option key={product.sku} value={product.sku}>
                            {product.sku} - {product.name}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => assignUnmatchedToProduct(item.token)}
                        className="rounded-lg border border-cyan-500/60 px-3 py-2 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/10"
                      >
                        Assign alias
                      </button>
                    </div>
                    <div className="mt-2 truncate text-[11px] text-slate-400">
                      {item.sourceLine}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-700/60 bg-slate-900/70 p-6 shadow-[0_18px_60px_rgba(7,10,22,0.45)]">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">
                Product Database Editor ({dbProducts.length})
              </h2>
              <button
                type="button"
                onClick={saveDb}
                disabled={!dbPath || !desktop}
                className="rounded-lg bg-cyan-400 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-300"
              >
                Save Database
              </button>
            </div>
            <div className="mb-3 text-xs text-slate-400">
              {dbStatus || 'Load a database to edit products.'}
            </div>
            <div className="mb-3 flex items-center gap-3 text-xs">
              <label className="inline-flex items-center gap-2 text-slate-300">
                <input
                  type="checkbox"
                  checked={autoSaveDb}
                  onChange={(e) => setAutoSaveDb(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-500 bg-slate-950 text-cyan-400"
                />
                Auto-save DB changes
              </label>
              {autoSavingDb && <span className="text-cyan-300">Saving...</span>}
              {!autoSavingDb && dbDirty && (
                <span className="text-amber-300">Unsaved edits</span>
              )}
            </div>
            <div className="max-h-[380px] overflow-auto rounded-xl border border-slate-700/60">
              <table className="min-w-full text-xs">
                <thead className="bg-slate-950/80 text-slate-300">
                  <tr>
                    <th className="px-2 py-2 text-left">SKU</th>
                    <th className="px-2 py-2 text-left">Name</th>
                    <th className="px-2 py-2 text-left">Unit Price</th>
                    <th className="px-2 py-2 text-left">Aliases (comma separated)</th>
                  </tr>
                </thead>
                <tbody>
                  {dbProducts.map((product, index) => (
                    <tr key={`${product.sku}-${index}`} className="border-t border-slate-800">
                      <td className="px-2 py-1">
                        <input
                          value={product.sku}
                          onChange={(e) =>
                            updateProduct(index, 'sku', e.target.value)
                          }
                          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          value={product.name}
                          onChange={(e) =>
                            updateProduct(index, 'name', e.target.value)
                          }
                          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          value={String(product.unitPrice)}
                          onChange={(e) =>
                            updateProduct(index, 'unitPrice', e.target.value)
                          }
                          className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <input
                          value={product.aliases.join(', ')}
                          onChange={(e) =>
                            updateProduct(index, 'aliases', e.target.value)
                          }
                          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-100"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
