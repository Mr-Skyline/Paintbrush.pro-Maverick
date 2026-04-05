import { useProjectStore } from '@/store/projectStore';
import type { TakeoffTool } from '@/types';
import { downloadCsv, downloadXlsx } from '@/utils/exportTakeoff';

const TOOLS: { id: TakeoffTool; label: string; title?: string }[] = [
  { id: 'select', label: 'Select' },
  { id: 'pan', label: 'Pan' },
  { id: 'ai_scope', label: 'AI box', title: 'Draw a box around what Grok should focus on' },
  { id: 'line', label: 'Line' },
  { id: 'polyline', label: 'Polyline' },
  { id: 'polygon', label: 'Area' },
  { id: 'arc', label: 'Arc' },
  { id: 'count', label: 'Count' },
  { id: 'measure', label: 'Measure' },
  { id: 'text', label: 'Note' },
];

export function ToolbarOST({
  onProjects,
  onOpenUpload,
  onOpenBoost,
  onFindSimilar,
  onFitView,
  onSaveProject,
  onSyncDisk,
  onExportPaintbrush,
  onDownloadZip,
}: {
  onProjects: () => void;
  onOpenUpload: () => void;
  onOpenBoost: () => void;
  onFindSimilar: () => void;
  onFitView: () => void;
  onSaveProject: () => void;
  onSyncDisk: () => void;
  onExportPaintbrush: () => void;
  onDownloadZip: () => void;
}) {
  const tool = useProjectStore((s) => s.tool);
  const setTool = useProjectStore((s) => s.setTool);
  const conditions = useProjectStore((s) => s.conditions);
  const selected = useProjectStore((s) => s.selectedConditionIds);
  const pixelsPerFoot = useProjectStore((s) => s.pixelsPerFoot);
  const currentPage = useProjectStore((s) => s.currentPage);
  const totalPages = useProjectStore((s) => s.totalPages);
  const setPage = useProjectStore((s) => s.setPage);
  const toolModes = useProjectStore((s) => s.toolModes);
  const setToolModes = useProjectStore((s) => s.setToolModes);
  const projectName = useProjectStore((s) => s.projectName);
  const documents = useProjectStore((s) => s.documents);

  const exportRows = () => {
    const fn = (
      window as unknown as { __takeoffExport?: () => import('@/utils/exportTakeoff').ExportRow[] }
    ).__takeoffExport;
    return fn?.() ?? [];
  };

  return (
    <header className="border-b border-ost-border bg-gradient-to-b from-[#161c27] to-[#12151c] px-3 py-3 shadow-lg">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onProjects}
            className="rounded-lg border border-ost-border bg-black/30 px-3 py-2 text-sm font-medium hover:bg-white/10"
          >
            Projects
          </button>
          <button
            type="button"
            onClick={onOpenUpload}
            className="rounded-lg border border-blue-500/50 bg-blue-600/20 px-3 py-2 text-sm font-medium text-blue-100 hover:bg-blue-600/30"
          >
            Upload plans
          </button>
          <button
            type="button"
            onClick={onOpenBoost}
            className="rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 px-4 py-2 text-sm font-bold shadow-lg hover:from-emerald-500 hover:to-teal-500"
          >
            Run AI Takeoff
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-ost-border bg-black/30 px-2 py-1 text-slate-200">
            {projectName || 'Untitled project'}
          </span>
          <span className="rounded-full border border-ost-border bg-black/30 px-2 py-1 text-ost-muted">
            {documents.length} plan{documents.length === 1 ? '' : 's'}
          </span>
          <span className="rounded-full border border-ost-border bg-black/30 px-2 py-1 text-ost-muted">
            Sheet {totalPages ? currentPage : '—'} / {totalPages || '—'}
          </span>
        </div>
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-[1fr_auto_auto]">
        <div className="min-w-0 rounded-lg border border-ost-border/80 bg-black/25 p-2">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ost-muted">
              Tools
            </span>
            <span className="text-[11px] text-ost-muted">
              Active: <span className="text-slate-200">{tool.replace('_', ' ')}</span>
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {TOOLS.map((t) => (
              <button
                key={t.id}
                type="button"
                title={t.title ?? t.label}
                onClick={() => setTool(t.id)}
                className={`rounded px-2.5 py-1.5 text-xs font-medium ${
                  tool === t.id
                    ? 'bg-blue-600 text-white'
                    : 'bg-black/30 text-slate-300 hover:bg-white/10'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-ost-border/80 bg-black/25 p-2">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ost-muted">
            Sheet + canvas
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setPage(currentPage - 1)}
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10 disabled:opacity-40"
            >
              ◀ Prev
            </button>
            <button
              type="button"
              disabled={!totalPages || currentPage >= totalPages}
              onClick={() => setPage(currentPage + 1)}
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10 disabled:opacity-40"
            >
              Next ▶
            </button>
            <button
              type="button"
              onClick={onFindSimilar}
              className="rounded border border-amber-600/50 px-2 py-1 text-xs text-amber-200 hover:bg-amber-900/20"
            >
              Auto count
            </button>
            <button
              type="button"
              onClick={onFitView}
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10"
            >
              Fit view
            </button>
            <button
              type="button"
              onClick={() =>
                (
                  window as unknown as { __takeoffUndo?: () => void }
                ).__takeoffUndo?.()
              }
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10"
            >
              Undo
            </button>
            <button
              type="button"
              onClick={() =>
                (
                  window as unknown as { __takeoffRedo?: () => void }
                ).__takeoffRedo?.()
              }
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10"
            >
              Redo
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-ost-border/80 bg-black/25 p-2">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ost-muted">
            Conditions + output
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <select
              className="max-w-[180px] rounded border border-ost-border bg-black/40 px-2 py-1.5 text-xs"
              value={selected[0] ?? ''}
              onChange={(e) =>
                useProjectStore.getState().setSelectedConditions(
                  e.target.value ? [e.target.value] : []
                )
              }
            >
              <option value="">— Condition —</option>
              {conditions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>

            <label className="flex items-center gap-1 rounded border border-ost-border px-2 py-1 text-[11px] text-ost-muted">
              px/ft
              <input
                type="number"
                min={1}
                className="w-12 rounded border border-ost-border bg-black/40 px-1 py-0.5 text-xs"
                value={pixelsPerFoot}
                onChange={(e) =>
                  useProjectStore.getState().setPixelsPerFoot(+e.target.value || 48)
                }
              />
            </label>

            <label className="flex cursor-pointer items-center gap-1 text-[11px] text-ost-muted">
              <input
                type="checkbox"
                checked={toolModes.continuousLinear}
                onChange={(e) =>
                  setToolModes({ continuousLinear: e.target.checked })
                }
              />
              Chain
            </label>
            <label className="flex cursor-pointer items-center gap-1 text-[11px] text-ost-muted">
              <input
                type="checkbox"
                checked={toolModes.alignGrid}
                onChange={(e) => setToolModes({ alignGrid: e.target.checked })}
              />
              Grid
            </label>
            <label className="flex cursor-pointer items-center gap-1 text-[11px] text-ost-muted">
              <input
                type="checkbox"
                checked={toolModes.backoffArea}
                onChange={(e) => setToolModes({ backoffArea: e.target.checked })}
              />
              Backout
            </label>

            <button
              type="button"
              onClick={onSaveProject}
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10"
            >
              Save
            </button>
            <button
              type="button"
              onClick={onSyncDisk}
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10"
            >
              Sync
            </button>
            <button
              type="button"
              onClick={onExportPaintbrush}
              className="rounded border border-violet-700/60 px-2 py-1 text-xs text-violet-200 hover:bg-violet-900/30"
            >
              Paintbrush CSV
            </button>
            <button
              type="button"
              onClick={onDownloadZip}
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10"
            >
              Zip
            </button>
            <button
              type="button"
              onClick={() => downloadCsv(exportRows())}
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10"
            >
              CSV
            </button>
            <button
              type="button"
              onClick={() => downloadXlsx(exportRows())}
              className="rounded border border-ost-border px-2 py-1 text-xs hover:bg-white/10"
            >
              XLSX
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
