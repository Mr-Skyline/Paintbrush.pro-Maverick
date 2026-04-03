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
  onOpenBoost,
  onSaveProject,
  onSyncDisk,
  onExportPaintbrush,
  onDownloadZip,
}: {
  onProjects: () => void;
  onOpenBoost: () => void;
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
  const toolModes = useProjectStore((s) => s.toolModes);
  const setToolModes = useProjectStore((s) => s.setToolModes);

  const exportRows = () => {
    const fn = (
      window as unknown as { __takeoffExport?: () => import('@/utils/exportTakeoff').ExportRow[] }
    ).__takeoffExport;
    return fn?.() ?? [];
  };

  return (
    <header className="flex flex-wrap items-center gap-2 border-b border-ost-border bg-ost-panel px-3 py-2">
      <button
        type="button"
        onClick={onProjects}
        className="rounded-lg bg-slate-800 px-3 py-2 text-sm font-medium hover:bg-slate-700"
      >
        Projects
      </button>

      <div className="h-6 w-px bg-ost-border" />

      <select
        className="max-w-[200px] rounded border border-ost-border bg-black/40 px-2 py-1.5 text-sm"
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
      <span className="text-xs text-ost-muted">Ctrl+click list = multi</span>

      <div className="h-6 w-px bg-ost-border" />

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

      <div className="h-6 w-px bg-ost-border" />

      <label className="flex cursor-pointer items-center gap-1 text-[10px] text-ost-muted">
        <input
          type="checkbox"
          checked={toolModes.continuousLinear}
          onChange={(e) =>
            setToolModes({ continuousLinear: e.target.checked })
          }
        />
        Chain
      </label>
      <label className="flex cursor-pointer items-center gap-1 text-[10px] text-ost-muted">
        <input
          type="checkbox"
          checked={toolModes.alignGrid}
          onChange={(e) => setToolModes({ alignGrid: e.target.checked })}
        />
        Grid snap
      </label>
      <label className="flex cursor-pointer items-center gap-1 text-[10px] text-ost-muted">
        <input
          type="checkbox"
          checked={toolModes.backoffArea}
          onChange={(e) => setToolModes({ backoffArea: e.target.checked })}
        />
        Backout
      </label>

      <div className="h-6 w-px bg-ost-border" />

      <button
        type="button"
        onClick={onOpenBoost}
        className="rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 px-4 py-2 text-sm font-bold shadow-lg hover:from-emerald-500 hover:to-teal-500"
      >
        Run Takeoff Boost
      </button>

      <div className="h-6 w-px bg-ost-border" />

      <button
        type="button"
        onClick={onSaveProject}
        className="rounded bg-blue-900/50 px-2 py-1 text-xs hover:bg-blue-800/50"
      >
        Save
      </button>
      <button
        type="button"
        onClick={onSyncDisk}
        className="rounded bg-black/30 px-2 py-1 text-xs hover:bg-white/10"
      >
        Sync disk
      </button>
      <button
        type="button"
        onClick={onExportPaintbrush}
        className="rounded bg-violet-900/40 px-2 py-1 text-xs text-violet-200 hover:bg-violet-800/40"
      >
        Paintbrush CSV
      </button>
      <button
        type="button"
        onClick={onDownloadZip}
        className="rounded bg-black/30 px-2 py-1 text-xs hover:bg-white/10"
      >
        Zip
      </button>

      <div className="h-6 w-px bg-ost-border" />

      <label className="flex items-center gap-1 text-xs text-ost-muted">
        px/ft
        <input
          type="number"
          min={1}
          className="w-14 rounded border border-ost-border bg-black/40 px-1 py-1"
          value={pixelsPerFoot}
          onChange={(e) =>
            useProjectStore.getState().setPixelsPerFoot(+e.target.value || 48)
          }
        />
      </label>

      <span className="text-xs text-ost-muted">
        Pg {totalPages ? currentPage : '—'}/{totalPages || '—'}
      </span>

      <div className="h-6 w-px bg-ost-border" />

      <button
        type="button"
        onClick={() => (window as unknown as { __takeoffUndo?: () => void }).__takeoffUndo?.()}
        className="rounded bg-black/30 px-2 py-1 text-xs hover:bg-white/10"
      >
        Undo
      </button>
      <button
        type="button"
        onClick={() => (window as unknown as { __takeoffRedo?: () => void }).__takeoffRedo?.()}
        className="rounded bg-black/30 px-2 py-1 text-xs hover:bg-white/10"
      >
        Redo
      </button>

      <button
        type="button"
        onClick={() => downloadCsv(exportRows())}
        className="rounded bg-black/30 px-2 py-1 text-xs hover:bg-white/10"
      >
        CSV
      </button>
      <button
        type="button"
        onClick={() => downloadXlsx(exportRows())}
        className="rounded bg-black/30 px-2 py-1 text-xs hover:bg-white/10"
      >
        Excel
      </button>
    </header>
  );
}
