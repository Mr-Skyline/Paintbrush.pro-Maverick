import { AgentTracePanel } from '@/components/AgentTracePanel';
import { CanvasWorkspace } from '@/components/CanvasWorkspace';
import { BoostDialog } from '@/components/BoostDialog';
import { ReviewPanel } from '@/components/ReviewPanel';
import { RightSidebarProperties } from '@/components/RightSidebarProperties';
import { SidebarLeft } from '@/components/SidebarLeft';
import { StatusBar } from '@/components/StatusBar';
import { ToolbarOST } from '@/components/ToolbarOST';
import { VoiceControls } from '@/components/VoiceControls';
import { useAutoSave } from '@/hooks/useAutoSave';
import { loadPdfBlob, savePdfBlob } from '@/lib/indexedProjectDb';
import { buildOstProjectFile } from '@/lib/serializeOst';
import { exportCsvToFileSystem, syncProjectToFileSystem } from '@/lib/fsSync';
import { saveProjectToIndexedDb } from '@/lib/projectPersistence';
import { downloadProjectZip } from '@/lib/zipExport';
import { downloadPaintbrushCsv } from '@/lib/paintbrushExport';
import { setAgentHostHandlers } from '@/agent/agentHost';
import {
  downloadAgentTraceJsonl,
  endAgentTraceSession,
  getCurrentAgentTraceSessionId,
  listAgentTraceEvents,
  recordAgentTrace,
  startAgentTraceSession,
} from '@/lib/agentTrace';
import { replayAgentTraceEvents } from '@/lib/agentReplay';
import { useNavigationStore } from '@/store/navigationStore';
import { useProjectStore } from '@/store/projectStore';
import type { TakeoffTool } from '@/types';
import { applyBoostReviewApproveAll } from '@/utils/boostReviewApply';
import { getAiFocusBoundingRectPx } from '@/utils/aiFocusContext';
import { runTakeoffBoostOnPage } from '@/utils/takeoffBoost';
import { findSimilarMarks } from '@/utils/findSimilar';
import type { ExportRow } from '@/utils/exportTakeoff';
import { fabric } from 'fabric';
import { openPdfFromArrayBuffer } from '@/utils/openPdfFromArrayBuffer';
import { useCallback, useEffect, useState } from 'react';

const TAKEOFF_TOOLS: TakeoffTool[] = [
  'select',
  'pan',
  'ai_scope',
  'line',
  'polyline',
  'polygon',
  'arc',
  'count',
  'measure',
  'text',
];

function isTakeoffTool(x: unknown): x is TakeoffTool {
  return typeof x === 'string' && (TAKEOFF_TOOLS as string[]).includes(x);
}

type BoostRunResult = { ok: boolean; error?: string; headline?: string };

export function WorkspaceLayout() {
  const [pdfData, setPdfData] = useState<ArrayBuffer | null>(null);
  const [boostOpen, setBoostOpen] = useState(false);
  const [tracePanelOpen, setTracePanelOpen] = useState(false);
  const [traceUiTick, setTraceUiTick] = useState(0);

  const openProjectId = useNavigationStore((s) => s.openProjectId);
  const goProjects = useNavigationStore((s) => s.goToProjects);
  const activeDocumentId = useProjectStore((s) => s.activeDocumentId);
  const currentPage = useProjectStore((s) => s.currentPage);
  const conditions = useProjectStore((s) => s.conditions);
  const setBoostReview = useProjectStore((s) => s.setBoostReview);
  const setPage = useProjectStore((s) => s.setPage);
  const totalPages = useProjectStore((s) => s.totalPages);
  const projectId = useProjectStore((s) => s.projectId);
  const documents = useProjectStore((s) => s.documents);
  const tool = useProjectStore((s) => s.tool);

  useAutoSave(!!projectId);

  useEffect(() => {
    const st0 = useProjectStore.getState();
    startAgentTraceSession({
      projectId: st0.projectId ?? null,
      activeDocumentId: st0.activeDocumentId ?? null,
      currentPage: st0.currentPage,
      totalPages: st0.totalPages ?? 0,
    });
    return () => {
      const sid = getCurrentAgentTraceSessionId();
      const st = useProjectStore.getState();
      const meta = {
        projectId: st.projectId ?? null,
        activeDocumentId: st.activeDocumentId ?? null,
        currentPage: st.currentPage,
        totalPages: st.totalPages ?? 0,
      };
      if (sid) endAgentTraceSession(sid, meta);
    };
  }, []);

  useEffect(() => {
    if (!openProjectId || !activeDocumentId) {
      setPdfData(null);
      return;
    }
    let cancelled = false;
    void loadPdfBlob(openProjectId, activeDocumentId).then((buf) => {
      if (!cancelled) setPdfData(buf ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [openProjectId, activeDocumentId]);

  useEffect(() => {
    if (!activeDocumentId || !totalPages) return;
    recordAgentTrace({
      event: 'sheet_selected',
      category: 'action',
      result: 'success',
      context: {
        documentId: activeDocumentId,
        page: currentPage,
        totalPages,
      },
    });
  }, [activeDocumentId, currentPage, totalPages]);

  useEffect(() => {
    recordAgentTrace({
      event: 'tool_selected',
      category: 'action',
      result: 'success',
      context: { tool },
    });
  }, [tool]);

  const runBoost = useCallback(
    async (scope: 'page' | 'all'): Promise<BoostRunResult> => {
      recordAgentTrace({
        event: 'run_ai_takeoff_started',
        category: 'action',
        result: 'neutral',
        context: { scope },
      });
      if (!pdfData) {
        recordAgentTrace({
          event: 'run_ai_takeoff_ended',
          category: 'outcome',
          result: 'error',
          context: { scope, error: 'No PDF loaded for this sheet.' },
        });
        return { ok: false, error: 'No PDF loaded for this sheet.' };
      }
      try {
        const doc = await openPdfFromArrayBuffer(pdfData);
        const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
          .__takeoffCanvas;
        const w = c?.getWidth() ?? 800;
        const h = c?.getHeight() ?? 600;
        if (scope === 'page') {
          const page = await doc.getPage(currentPage);
          const aiFocus = getAiFocusBoundingRectPx(c ?? undefined);
          const review = await runTakeoffBoostOnPage(
            page,
            currentPage - 1,
            w,
            h,
            conditions,
            aiFocus
          );
          setBoostReview(review);
          recordAgentTrace({
            event: 'run_ai_takeoff_ended',
            category: 'outcome',
            result: 'success',
            context: { scope, headline: review.headline },
          });
          return { ok: true, headline: review.headline };
        }
        const page = await doc.getPage(1);
        const review = await runTakeoffBoostOnPage(
          page,
          0,
          w,
          h,
          conditions,
          null
        );
        review.headline = `[All pages stub] ${review.headline}`;
        setBoostReview(review);
        recordAgentTrace({
          event: 'run_ai_takeoff_ended',
          category: 'outcome',
          result: 'success',
          context: { scope, headline: review.headline },
        });
        return { ok: true, headline: review.headline };
      } catch (e) {
        recordAgentTrace({
          event: 'run_ai_takeoff_ended',
          category: 'outcome',
          result: 'error',
          context: { scope, error: String(e) },
        });
        return { ok: false, error: String(e) };
      }
    },
    [pdfData, currentPage, conditions, setBoostReview]
  );

  useEffect(() => {
    setAgentHostHandlers({
      runBoost,
      openBoostDialog: () => setBoostOpen(true),
      goToProjects: () => goProjects(),
      saveProject: async () => {
        try {
          await saveProjectToIndexedDb();
          return { ok: true };
        } catch (e) {
          return { ok: false, error: String(e) };
        }
      },
    });
    return () => setAgentHostHandlers({});
  }, [runBoost, goProjects]);

  const exportRows = (): ExportRow[] => {
    const fn = (
      window as unknown as { __takeoffExport?: () => ExportRow[] }
    ).__takeoffExport;
    return fn?.() ?? [];
  };

  const findSimilar = () => {
    recordAgentTrace({
      event: 'workspace_find_similar_invoked',
      category: 'action',
      result: 'neutral',
    });
    const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
      .__takeoffCanvas;
    if (!c) {
      recordAgentTrace({
        event: 'workspace_find_similar_result',
        category: 'outcome',
        result: 'error',
        context: { reason: 'no_canvas' },
      });
      return;
    }
    const a = c.getActiveObject();
    if (!a) {
      recordAgentTrace({
        event: 'workspace_find_similar_result',
        category: 'outcome',
        result: 'neutral',
        context: { reason: 'no_selection' },
      });
      alert('Select a mark first.');
      return;
    }
    const sim = findSimilarMarks(c, a);
    if (!sim.length) {
      recordAgentTrace({
        event: 'workspace_find_similar_result',
        category: 'outcome',
        result: 'neutral',
        context: { reason: 'no_matches' },
      });
      alert('No similar marks found.');
      return;
    }
    const sel = sim
      .map((s) =>
        c
          .getObjects()
          .find((o) => (o as fabric.Object & { nid?: string }).nid === s.objectNid)
      )
      .filter(Boolean) as fabric.Object[];
    if (sel.length) {
      const grp = new fabric.ActiveSelection(sel, { canvas: c });
      c.setActiveObject(grp);
      c.requestRenderAll();
    }
    recordAgentTrace({
      event: 'workspace_find_similar_result',
      category: 'outcome',
      result: 'success',
      context: { selectedCount: sel.length },
    });
    alert(`Selected ${sel.length} similar marks.`);
  };

  const onDropPdf = async (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (!f || !/\.pdf$/i.test(f.name) || !projectId) return;
    recordAgentTrace({
      event: 'workspace_pdf_upload_started',
      category: 'action',
      result: 'neutral',
      context: { fileName: f.name },
    });
    try {
      const buf = await f.arrayBuffer();
      const docId = crypto.randomUUID();
      await savePdfBlob(projectId, docId, buf);
      const doc = await openPdfFromArrayBuffer(buf);
      useProjectStore.getState().addPdfDocument(docId, f.name, doc.numPages);
      useProjectStore.getState().setActiveDocument(docId);
      setPdfData(buf);
      await saveProjectToIndexedDb();
      recordAgentTrace({
        event: 'workspace_pdf_upload_completed',
        category: 'outcome',
        result: 'success',
        context: { fileName: f.name, documentId: docId, numPages: doc.numPages },
      });
    } catch (err) {
      console.error(err);
      recordAgentTrace({
        event: 'workspace_pdf_upload_failed',
        category: 'outcome',
        result: 'error',
        context: { fileName: f.name, error: String(err) },
      });
      alert('Could not add PDF.');
    }
  };

  const saveManual = async () => {
    try {
      await saveProjectToIndexedDb();
      recordAgentTrace({
        event: 'workspace_save_manual',
        category: 'outcome',
        result: 'success',
      });
      alert('Saved to browser storage.');
    } catch (e) {
      recordAgentTrace({
        event: 'workspace_save_manual',
        category: 'outcome',
        result: 'error',
        context: { error: String(e) },
      });
      alert(String(e));
    }
  };

  const syncDisk = async () => {
    const ok = await syncProjectToFileSystem();
    recordAgentTrace({
      event: 'workspace_sync_disk',
      category: 'action',
      result: ok ? 'success' : 'error',
      context: { ok },
    });
    alert(
      ok
        ? 'Synced to linked workspace folder.'
        : 'Link a folder from Projects screen (Chrome/Edge) or sync failed.'
    );
  };

  const exportPb = async () => {
    recordAgentTrace({
      event: 'workspace_export_paintbrush',
      category: 'action',
      result: 'neutral',
    });
    const rows = exportRows();
    downloadPaintbrushCsv(rows);
    const ok = await exportCsvToFileSystem(rows, `takeoff-${Date.now()}.csv`);
    recordAgentTrace({
      event: 'workspace_export_paintbrush',
      category: 'outcome',
      result: 'success',
      context: { rowCount: rows.length, wroteToDisk: ok },
    });
    recordAgentTrace({
      event: 'export_paintbrush_csv',
      category: 'action',
      result: 'success',
      context: { rowCount: rows.length, wroteToDisk: ok },
    });
    if (ok) alert('Also wrote CSV to exports/ on disk.');
  };

  const replayLastSupportedActions = useCallback(async (opts?: { dryRun?: boolean; sessionOnly?: boolean }) => {
    const all = listAgentTraceEvents();
    const source = opts?.sessionOnly && getCurrentAgentTraceSessionId()
      ? all.filter((e) => e.sessionId === getCurrentAgentTraceSessionId())
      : all;
    const recent = source.slice(-200);
    let runAiFailures = 0;
    const dryRun = opts?.dryRun === true;
    const sessionOnly = opts?.sessionOnly === true;
    recordAgentTrace({
      event: dryRun ? 'trace_replay_dry_run_started' : 'trace_replay_started',
      category: 'action',
      result: 'neutral',
      context: {
        dryRun,
        sessionOnly,
        sourceWindowSize: 200,
        sourceEventCount: recent.length,
      },
    });

    const res = await replayAgentTraceEvents(recent, {
      set_tool: async ({ tool: t }) => {
        if (!isTakeoffTool(t)) return;
        useProjectStore.getState().setTool(t);
      },
      set_page: async ({ documentId, page }) => {
        const st = useProjectStore.getState();
        if (!st.documents.some((d) => d.id === documentId)) return;
        st.setActiveDocument(documentId);
        if (page !== undefined) st.setPage(page);
      },
      run_ai_takeoff: async ({ context: ctx }) => {
        const scope = ctx?.scope;
        if (scope !== 'page' && scope !== 'all') return;
        const r = await runBoost(scope);
        if (!r.ok) runAiFailures += 1;
      },
      approve_review: async () => {
        applyBoostReviewApproveAll();
      },
      export_outputs: async () => {
        await exportPb();
      },
    }, { dryRun });

    setTraceUiTick((n) => n + 1);
    const { applied, skipped, failed } = res.counts;
    recordAgentTrace({
      event: dryRun ? 'trace_replay_dry_run_completed' : 'trace_replay_completed',
      category: 'outcome',
      result: failed > 0 || runAiFailures > 0 ? 'error' : 'success',
      context: {
        dryRun,
        sessionOnly,
        sourceEventCount: recent.length,
        appliedCount: applied,
        skippedCount: skipped,
        failedCount: failed,
        runAiFailures,
      },
    });
    const modePrefix = dryRun ? 'Replay dry-run' : 'Replay';
    const scopeSuffix = sessionOnly ? ' (session)' : '';
    const msg = `${modePrefix}${scopeSuffix}: ${res.outcomes.length} events, applied ${applied}, skipped ${skipped}, failed ${failed}${
      runAiFailures ? `, run AI failures ${runAiFailures}` : ''
    }.`;
    if (recent.length === 0) {
      alert('No events in recent trace window.');
    } else {
      alert(msg);
    }
  }, [runBoost, exportPb]);

  const downloadZip = async () => {
    if (!projectId) {
      recordAgentTrace({
        event: 'workspace_download_zip',
        category: 'outcome',
        result: 'neutral',
        context: { reason: 'no_project' },
      });
      return;
    }
    recordAgentTrace({
      event: 'workspace_download_zip_started',
      category: 'action',
      result: 'neutral',
      context: { projectId },
    });
    try {
      const ost = buildOstProjectFile();
      const parts: { relativePath: string; buffer: ArrayBuffer }[] = [];
      for (const d of documents) {
        const buf = await loadPdfBlob(projectId, d.id);
        if (buf)
          parts.push({
            relativePath: `pdfs/${d.name.replace(/[^\w.-]+/g, '_')}`,
            buffer: buf,
          });
      }
      await downloadProjectZip(projectId, ost.projectName, ost, parts);
      recordAgentTrace({
        event: 'workspace_download_zip',
        category: 'outcome',
        result: 'success',
        context: { pdfParts: parts.length },
      });
    } catch (e) {
      recordAgentTrace({
        event: 'workspace_download_zip',
        category: 'outcome',
        result: 'error',
        context: { error: String(e) },
      });
      throw e;
    }
  };

  const goPage = (next: number, direction: 'prev' | 'next') => {
    recordAgentTrace({
      event: 'workspace_page_nav',
      category: 'action',
      result: 'success',
      context: { direction, from: currentPage, to: next },
    });
    setPage(next);
  };

  useEffect(() => {
    const onExport = () => {
      try {
        downloadAgentTraceJsonl();
        alert('Agent trace exported (JSON Lines download).');
      } catch (e) {
        alert(`Trace export failed: ${String(e)}`);
      }
    };
    window.addEventListener('agent-trace:export', onExport);
    return () => window.removeEventListener('agent-trace:export', onExport);
  }, []);

  return (
    <div
      className="flex h-full flex-col"
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDropPdf}
    >
      <ToolbarOST
        onProjects={goProjects}
        onOpenBoost={() => setBoostOpen(true)}
        onSaveProject={saveManual}
        onSyncDisk={syncDisk}
        onExportPaintbrush={exportPb}
        onDownloadZip={downloadZip}
      />
      <div className="flex min-h-0 flex-1">
        <SidebarLeft />
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex flex-wrap items-center gap-2 border-b border-ost-border bg-ost-panel/80 px-2 py-1 text-xs text-ost-muted">
            <span>Drop PDF here to add sheets</span>
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => goPage(currentPage - 1, 'prev')}
              className="rounded px-2 py-1 hover:bg-white/10 disabled:opacity-30"
            >
              ◀ Prev
            </button>
            <button
              type="button"
              disabled={!totalPages || currentPage >= totalPages}
              onClick={() => goPage(currentPage + 1, 'next')}
              className="rounded px-2 py-1 hover:bg-white/10 disabled:opacity-30"
            >
              Next ▶
            </button>
            <button
              type="button"
              onClick={findSimilar}
              className="ml-2 rounded border border-amber-600/50 px-2 py-1 text-amber-200 hover:bg-amber-900/20"
            >
              Auto count / Find similar
            </button>
            <button
              type="button"
              onClick={() => {
                const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
                  .__takeoffCanvas;
                c?.setViewportTransform([1, 0, 0, 1, 0, 0]);
                const pc = document.querySelector('.pdf-canvas') as HTMLElement;
                if (pc) pc.style.transform = '';
                c?.requestRenderAll();
              }}
              className="rounded px-2 py-1 hover:bg-white/10"
            >
              Fit view
            </button>
            <button
              type="button"
              onClick={() => setTracePanelOpen((o) => !o)}
              className="ml-auto rounded border border-ost-border px-2 py-1 text-ost-muted hover:bg-white/10"
            >
              {tracePanelOpen ? 'Hide trace' : 'Trace'}
            </button>
          </div>
          {tracePanelOpen ? (
            <AgentTracePanel
              refreshKey={traceUiTick}
              onAfterMutate={() => setTraceUiTick((n) => n + 1)}
              onReplay={() => void replayLastSupportedActions()}
              onReplayDryRun={() => void replayLastSupportedActions({ dryRun: true })}
              onReplaySession={() => void replayLastSupportedActions({ sessionOnly: true })}
              onReplaySessionDryRun={() =>
                void replayLastSupportedActions({ dryRun: true, sessionOnly: true })
              }
            />
          ) : null}
          <div className="min-h-0 flex-1 overflow-auto p-2">
            <CanvasWorkspace pdfData={pdfData} />
          </div>
          <VoiceControls />
        </main>
        <RightSidebarProperties />
      </div>
      <StatusBar />
      <ReviewPanel />
      <BoostDialog
        open={boostOpen}
        onClose={() => setBoostOpen(false)}
        onRun={(scope) => {
          void runBoost(scope).then((r) => {
            if (!r.ok && r.error) alert(r.error);
          });
        }}
      />
    </div>
  );
}
