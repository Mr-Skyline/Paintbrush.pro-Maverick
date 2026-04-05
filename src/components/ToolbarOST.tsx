import { useProjectStore } from '@/store/projectStore';
import {
  clearAgentTraceEvents,
  recordAgentTrace,
} from '@/lib/agentTrace';
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
  onExportTrace,
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
  onExportTrace: () => void;
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

  const setToolWithTrace = (nextTool: TakeoffTool) => {
    setTool(nextTool);
    recordAgentTrace({
      category: 'action',
      event: 'tool_selected',
      reason: 'Operator switched takeoff mode in ribbon tools.',
      result: 'success',
      context: {
        previousTool: tool,
        nextTool,
      },
    });
  };

  const setPageWithTrace = (nextPage: number, source: string) => {
    setPage(nextPage);
    recordAgentTrace({
      category: 'action',
      event: 'sheet_selected',
      reason: `Operator navigated to a different sheet via ${source}.`,
      result: 'success',
      context: {
        previousPage: currentPage,
        nextPage,
        totalPages,
      },
    });
  };

  const runUndoWithTrace = () => {
    (
      window as unknown as { __takeoffUndo?: () => void }
    ).__takeoffUndo?.();
    recordAgentTrace({
      category: 'action',
      event: 'undo',
      reason: 'Operator reverted the previous drawing/annotation step.',
      result: 'neutral',
      context: { page: currentPage },
    });
  };

  const runRedoWithTrace = () => {
    (
      window as unknown as { __takeoffRedo?: () => void }
    ).__takeoffRedo?.();
    recordAgentTrace({
      category: 'action',
      event: 'redo',
      reason: 'Operator re-applied a reverted drawing/annotation step.',
      result: 'neutral',
      context: { page: currentPage },
    });
  };

  const exportCsvWithTrace = () => {
    const rows = exportRows();
    downloadCsv(rows);
    recordAgentTrace({
      category: 'outcome',
      event: 'export_csv',
      reason: 'Operator exported quantified takeoff rows to CSV.',
      result: 'success',
      context: { rowCount: rows.length },
    });
  };

  const exportXlsxWithTrace = () => {
    const rows = exportRows();
    downloadXlsx(rows);
    recordAgentTrace({
      category: 'outcome',
      event: 'export_xlsx',
      reason: 'Operator exported quantified takeoff rows to XLSX.',
      result: 'success',
      context: { rowCount: rows.length },
    });
  };

  const exportTraceWithTrace = () => {
    onExportTrace();
    recordAgentTrace({
      category: 'outcome',
      event: 'export_agent_trace',
      reason:
        'Operator exported action/decision/outcome trace for agent training.',
      result: 'success',
    });
  };

  const clearTraceWithTrace = () => {
    clearAgentTraceEvents();
    recordAgentTrace({
      category: 'decision',
      event: 'agent_trace_reset',
      reason: 'Operator reset stored trace history before a clean run.',
      result: 'neutral',
    });
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
          <RibbonButton
            onClick={() => {
              onProjects();
              recordAgentTrace({
                category: 'action',
                event: 'open_projects_screen',
                reason: 'Operator switched from takeoff workspace to project list.',
                result: 'success',
              });
            }}
          >
            Projects
          </RibbonButton>
          <RibbonButton
            onClick={() => {
              onOpenUpload();
              recordAgentTrace({
                category: 'action',
                event: 'open_upload_dialog',
                reason: 'Operator initiated plan ingestion from local files.',
                result: 'neutral',
              });
            }}
          >
            Upload plans
          </RibbonButton>
          <RibbonButton
            onClick={() => {
              onSaveProject();
              recordAgentTrace({
                category: 'outcome',
                event: 'save_project',
                reason: 'Operator persisted current takeoff state.',
                result: 'success',
              });
            }}
          >
            Save
          </RibbonButton>
          <RibbonButton
            onClick={() => {
              onSyncDisk();
              recordAgentTrace({
                category: 'outcome',
                event: 'sync_project_to_disk',
                reason: 'Operator synchronized workspace state to linked filesystem.',
                result: 'neutral',
              });
            }}
          >
            Sync
          </RibbonButton>
        </RibbonGroup>

        <RibbonGroup title="Takeoff">
          <button
            type="button"
            onClick={() => {
              onOpenBoost();
              recordAgentTrace({
                category: 'decision',
                event: 'open_ai_takeoff_dialog',
                reason:
                  'Operator requested AI-assisted takeoff for current context.',
                result: 'neutral',
                context: { page: currentPage, sheetCount: totalPages },
              });
            }}
            className="rounded border border-emerald-500/60 bg-emerald-600/25 px-2 py-1 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-600/35"
          >
            Run AI Takeoff
          </button>
          <RibbonButton
            onClick={() => {
              onFindSimilar();
              recordAgentTrace({
                category: 'action',
                event: 'auto_count_find_similar',
                reason: 'Operator searched for similar marks to accelerate count takeoff.',
                result: 'neutral',
                context: { page: currentPage },
              });
            }}
          >
            Auto count
          </RibbonButton>
        </RibbonGroup>

        <RibbonGroup title="Tools">
          {quickTools.map((t) => (
            <button
              key={t.id}
              type="button"
              title={t.title ?? t.label}
              onClick={() => setToolWithTrace(t.id)}
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
              if (Number.isFinite(next) && next >= 1)
                setPageWithTrace(next, 'sheets_dropdown');
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
            onClick={() => setPageWithTrace(currentPage - 1, 'sheets_prev_button')}
            disabled={currentPage <= 1}
          >
            ◀
          </RibbonButton>
          <RibbonButton
            onClick={() => setPageWithTrace(currentPage + 1, 'sheets_next_button')}
            disabled={!totalPages || currentPage >= totalPages}
          >
            ▶
          </RibbonButton>
        </RibbonGroup>

        <RibbonGroup title="View">
          <RibbonButton
            onClick={() => {
              onFitView();
              recordAgentTrace({
                category: 'action',
                event: 'fit_view',
                reason: 'Operator reset zoom/pan to refocus on full sheet.',
                result: 'success',
              });
            }}
          >
            Fit view
          </RibbonButton>
          <RibbonButton onClick={runUndoWithTrace}>
            Undo
          </RibbonButton>
          <RibbonButton onClick={runRedoWithTrace}>
            Redo
          </RibbonButton>
          <label className="flex items-center gap-1 rounded border border-ost-border bg-black/30 px-2 py-1 text-[11px] text-ost-muted">
            px/ft
            <input
              type="number"
              min={1}
              className="w-12 rounded border border-ost-border bg-black/40 px-1 py-0.5 text-[11px]"
              value={pixelsPerFoot}
              onChange={(e) => {
                const next = +e.target.value || 48;
                useProjectStore.getState().setPixelsPerFoot(next);
                recordAgentTrace({
                  category: 'decision',
                  event: 'scale_updated',
                  reason: 'Operator calibrated measurement scale for takeoff accuracy.',
                  result: 'neutral',
                  context: { pixelsPerFoot: next },
                });
              }}
            />
          </label>
        </RibbonGroup>

        <RibbonGroup title="Output">
          <label className="flex items-center gap-1 text-[11px] text-ost-muted">
            <input
              type="checkbox"
              checked={toolModes.continuousLinear}
              onChange={(e) => {
                setToolModes({ continuousLinear: e.target.checked });
                recordAgentTrace({
                  category: 'decision',
                  event: 'toggle_continuous_linear',
                  reason:
                    'Operator toggled chained linear drawing behavior for repetitive takeoff.',
                  result: 'neutral',
                  context: { enabled: e.target.checked },
                });
              }}
            />
            Chain
          </label>
          <label className="flex items-center gap-1 text-[11px] text-ost-muted">
            <input
              type="checkbox"
              checked={toolModes.alignGrid}
              onChange={(e) => {
                setToolModes({ alignGrid: e.target.checked });
                recordAgentTrace({
                  category: 'decision',
                  event: 'toggle_grid_snap',
                  reason: 'Operator toggled grid snapping for controlled geometry placement.',
                  result: 'neutral',
                  context: { enabled: e.target.checked },
                });
              }}
            />
            Grid
          </label>
          <label className="flex items-center gap-1 text-[11px] text-ost-muted">
            <input
              type="checkbox"
              checked={toolModes.backoffArea}
              onChange={(e) => {
                setToolModes({ backoffArea: e.target.checked });
                recordAgentTrace({
                  category: 'decision',
                  event: 'toggle_backout_area',
                  reason:
                    'Operator toggled area backout behavior for deduction-aware quantities.',
                  result: 'neutral',
                  context: { enabled: e.target.checked },
                });
              }}
            />
            Backout
          </label>
          <RibbonButton
            onClick={() => {
              onExportPaintbrush();
              recordAgentTrace({
                category: 'outcome',
                event: 'export_paintbrush_csv',
                reason: 'Operator exported standardized Paintbrush CSV output.',
                result: 'success',
              });
            }}
          >
            Paintbrush CSV
          </RibbonButton>
          <RibbonButton
            onClick={() => {
              onDownloadZip();
              recordAgentTrace({
                category: 'outcome',
                event: 'export_project_zip',
                reason: 'Operator packaged workspace and plans into portable zip.',
                result: 'success',
              });
            }}
          >
            Zip
          </RibbonButton>
          <RibbonButton onClick={exportCsvWithTrace}>CSV</RibbonButton>
          <RibbonButton onClick={exportXlsxWithTrace}>XLSX</RibbonButton>
          <RibbonButton onClick={exportTraceWithTrace}>Export trace</RibbonButton>
          <RibbonButton onClick={clearTraceWithTrace}>Clear trace</RibbonButton>
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
