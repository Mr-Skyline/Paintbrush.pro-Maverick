import { useProjectStore } from '@/store/projectStore';
import type { TakeoffTool } from '@/types';
import { downloadCsv, downloadXlsx } from '@/utils/exportTakeoff';
import type { ReactNode } from 'react';

const TOOLS: { id: TakeoffTool; label: string; title?: string }[] = [
  { id: 'select', label: 'Select' },
  { id: 'pan', label: 'Pan' },
  { id: 'line', label: 'Line' },
  { id: 'polygon', label: 'Area' },
  { id: 'count', label: 'Count' },
  { id: 'measure', label: 'Measure' },
  {
    id: 'ai_scope',
    label: 'AI box',
    title: 'Draw a focus box for AI takeoff',
  },
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
  const pixelsPerFoot = useProjectStore((s) => s.pixelsPerFoot);
  const currentPage = useProjectStore((s) => s.currentPage);
  const totalPages = useProjectStore((s) => s.totalPages);
  const setPage = useProjectStore((s) => s.setPage);
  const toolModes = useProjectStore((s) => s.toolModes);
  const setToolModes = useProjectStore((s) => s.setToolModes);
  const projectName = useProjectStore((s) => s.projectName);
  const documents = useProjectStore((s) => s.documents);
  const quickTools = TOOLS;

  const exportRows = () => {
    const fn = (
      window as unknown as { __takeoffExport?: () => import('@/utils/exportTakeoff').ExportRow[] }
    ).__takeoffExport;
    return fn?.() ?? [];
  };

  return (
    <header className="border-b border-ost-border bg-gradient-to-b from-[#171c26] to-[#12161f] px-2 py-1.5 shadow-lg">
      <div className="flex items-center justify-between gap-2 border-b border-ost-border/70 pb-1.5">
        <div className="text-[11px] font-semibold tracking-wide text-slate-200">
          TAKEOFF HOME
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          <span className="rounded border border-ost-border bg-black/25 px-2 py-0.5 text-slate-200">
            {projectName || 'Untitled project'}
          </span>
          <span className="rounded border border-ost-border bg-black/25 px-2 py-0.5 text-ost-muted">
            {documents.length} plan{documents.length === 1 ? '' : 's'}
          </span>
          <span className="rounded border border-ost-border bg-black/25 px-2 py-0.5 text-ost-muted">
            Sheet {totalPages ? currentPage : '—'} / {totalPages || '—'}
          </span>
        </div>
      </div>

      <div className="mt-1.5 flex flex-wrap items-stretch gap-1.5">
        <RibbonGroup title="Project">
          <RibbonButton onClick={onProjects}>Projects</RibbonButton>
          <RibbonButton onClick={onOpenUpload}>Upload plans</RibbonButton>
          <RibbonButton onClick={onSaveProject}>Save</RibbonButton>
          <RibbonButton onClick={onSyncDisk}>Sync</RibbonButton>
        </RibbonGroup>

        <RibbonGroup title="Takeoff">
          <button
            type="button"
            onClick={onOpenBoost}
            className="rounded border border-emerald-500/60 bg-emerald-600/25 px-2 py-1 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-600/35"
          >
            Run AI Takeoff
          </button>
          <RibbonButton onClick={onFindSimilar}>Auto count</RibbonButton>
        </RibbonGroup>

        <RibbonGroup title="Tools">
          {quickTools.map((t) => (
            <button
              key={t.id}
              type="button"
              title={t.title ?? t.label}
              onClick={() => setTool(t.id)}
              className={`rounded border px-2 py-1 text-[11px] font-medium ${
                tool === t.id
                  ? 'border-blue-500 bg-blue-600 text-white'
                  : 'border-ost-border bg-black/30 text-slate-300 hover:bg-white/10'
              }`}
            >
              {t.label}
            </button>
          ))}
        </RibbonGroup>

        <RibbonGroup title="Sheets">
          <select
            className="min-w-[130px] rounded border border-ost-border bg-black/40 px-2 py-1 text-[11px]"
            value={totalPages ? String(currentPage) : ''}
            onChange={(e) => {
              const next = Number.parseInt(e.target.value, 10);
              if (Number.isFinite(next) && next >= 1) setPage(next);
            }}
            disabled={!totalPages}
          >
            {!totalPages && <option value="">No sheets loaded</option>}
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
              <option key={p} value={String(p)}>
                Sheet {p}
              </option>
            ))}
          </select>
          <RibbonButton
            onClick={() => setPage(currentPage - 1)}
            disabled={currentPage <= 1}
          >
            ◀
          </RibbonButton>
          <RibbonButton
            onClick={() => setPage(currentPage + 1)}
            disabled={!totalPages || currentPage >= totalPages}
          >
            ▶
          </RibbonButton>
        </RibbonGroup>

        <RibbonGroup title="View">
          <RibbonButton onClick={onFitView}>Fit view</RibbonButton>
          <RibbonButton
            onClick={() =>
              (window as unknown as { __takeoffUndo?: () => void }).__takeoffUndo?.()
            }
          >
            Undo
          </RibbonButton>
          <RibbonButton
            onClick={() =>
              (window as unknown as { __takeoffRedo?: () => void }).__takeoffRedo?.()
            }
          >
            Redo
          </RibbonButton>
          <label className="flex items-center gap-1 rounded border border-ost-border bg-black/30 px-2 py-1 text-[11px] text-ost-muted">
            px/ft
            <input
              type="number"
              min={1}
              className="w-12 rounded border border-ost-border bg-black/40 px-1 py-0.5 text-[11px]"
              value={pixelsPerFoot}
              onChange={(e) =>
                useProjectStore.getState().setPixelsPerFoot(+e.target.value || 48)
              }
            />
          </label>
        </RibbonGroup>

        <RibbonGroup title="Output">
          <label className="flex items-center gap-1 text-[11px] text-ost-muted">
            <input
              type="checkbox"
              checked={toolModes.continuousLinear}
              onChange={(e) => setToolModes({ continuousLinear: e.target.checked })}
            />
            Chain
          </label>
          <label className="flex items-center gap-1 text-[11px] text-ost-muted">
            <input
              type="checkbox"
              checked={toolModes.alignGrid}
              onChange={(e) => setToolModes({ alignGrid: e.target.checked })}
            />
            Grid
          </label>
          <label className="flex items-center gap-1 text-[11px] text-ost-muted">
            <input
              type="checkbox"
              checked={toolModes.backoffArea}
              onChange={(e) => setToolModes({ backoffArea: e.target.checked })}
            />
            Backout
          </label>
          <RibbonButton onClick={onExportPaintbrush}>Paintbrush CSV</RibbonButton>
          <RibbonButton onClick={onDownloadZip}>Zip</RibbonButton>
          <RibbonButton onClick={() => downloadCsv(exportRows())}>CSV</RibbonButton>
          <RibbonButton onClick={() => downloadXlsx(exportRows())}>XLSX</RibbonButton>
        </RibbonGroup>
      </div>
    </header>
  );
}

function RibbonGroup({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded border border-ost-border/70 bg-black/20 px-2 py-1">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ost-muted">
        {title}
      </div>
      <div className="flex flex-wrap items-center gap-1">{children}</div>
    </section>
  );
}

function RibbonButton({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded border border-ost-border bg-black/30 px-2 py-1 text-[11px] text-slate-300 hover:bg-white/10 disabled:opacity-40"
    >
      {children}
    </button>
  );
}
