import { CanvasWorkspace } from '@/components/CanvasWorkspace';
import { BoostDialog } from '@/components/BoostDialog';
import { ReviewPanel } from '@/components/ReviewPanel';
import { RightSidebarProperties } from '@/components/RightSidebarProperties';
import { SidebarLeft } from '@/components/SidebarLeft';
import { StatusBar } from '@/components/StatusBar';
import { ToolbarOST } from '@/components/ToolbarOST';
import { VoiceControls } from '@/components/VoiceControls';
import { TakeoffSidekickPanel } from '@/components/TakeoffSidekickPanel';
import { useAutoSave } from '@/hooks/useAutoSave';
import { loadPdfBlob, savePdfBlob } from '@/lib/indexedProjectDb';
import { buildOstProjectFile } from '@/lib/serializeOst';
import { exportCsvToFileSystem, syncProjectToFileSystem } from '@/lib/fsSync';
import { saveProjectToIndexedDb } from '@/lib/projectPersistence';
import { downloadProjectZip } from '@/lib/zipExport';
import { downloadPaintbrushCsv } from '@/lib/paintbrushExport';
import { setAgentHostHandlers } from '@/agent/agentHost';
import { useNavigationStore } from '@/store/navigationStore';
import { useProjectStore } from '@/store/projectStore';
import { getAiFocusBoundingRectPx } from '@/utils/aiFocusContext';
import { runTakeoffBoostOnPage } from '@/utils/takeoffBoost';
import { findSimilarMarks } from '@/utils/findSimilar';
import type { ExportRow } from '@/utils/exportTakeoff';
import { fabric } from 'fabric';
import { openPdfFromArrayBuffer } from '@/utils/openPdfFromArrayBuffer';
import { useCallback, useEffect, useState } from 'react';

type BoostRunResult = { ok: boolean; error?: string; headline?: string };

export function WorkspaceLayout() {
  const [pdfData, setPdfData] = useState<ArrayBuffer | null>(null);
  const [boostOpen, setBoostOpen] = useState(false);
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

  useAutoSave(!!projectId);

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

  const runBoost = useCallback(
    async (scope: 'page' | 'all'): Promise<BoostRunResult> => {
      if (!pdfData) {
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
        return { ok: true, headline: review.headline };
      } catch (e) {
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
    const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
      .__takeoffCanvas;
    if (!c) return;
    const a = c.getActiveObject();
    if (!a) {
      alert('Select a mark first.');
      return;
    }
    const sim = findSimilarMarks(c, a);
    if (!sim.length) {
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
    alert(`Selected ${sel.length} similar marks.`);
  };

  const onDropPdf = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const f = e.dataTransfer.files?.[0];
    if (!f || !/\.pdf$/i.test(f.name) || !projectId) return;
    try {
      const buf = await f.arrayBuffer();
      const docId = crypto.randomUUID();
      await savePdfBlob(projectId, docId, buf);
      const doc = await openPdfFromArrayBuffer(buf);
      useProjectStore.getState().addPdfDocument(docId, f.name, doc.numPages);
      useProjectStore.getState().setActiveDocument(docId);
      setPdfData(buf);
      await saveProjectToIndexedDb();
    } catch (err) {
      console.error(err);
      alert('Could not add PDF.');
    }
  };

  const saveManual = async () => {
    try {
      await saveProjectToIndexedDb();
      alert('Saved to browser storage.');
    } catch (e) {
      alert(String(e));
    }
  };

  const syncDisk = async () => {
    const ok = await syncProjectToFileSystem();
    alert(
      ok
        ? 'Synced to linked workspace folder.'
        : 'Link a folder from Projects screen (Chrome/Edge) or sync failed.'
    );
  };

  const exportPb = async () => {
    const rows = exportRows();
    downloadPaintbrushCsv(rows);
    const ok = await exportCsvToFileSystem(rows, `takeoff-${Date.now()}.csv`);
    if (ok) alert('Also wrote CSV to exports/ on disk.');
  };

  const downloadZip = async () => {
    if (!projectId) return;
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
    await downloadProjectZip(
      projectId,
      ost.projectName,
      ost,
      parts
    );
  };

  return (
    <div
      className="flex h-full flex-col"
      onDragOver={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onDragEnter={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
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
          <div className="flex items-center gap-2 border-b border-ost-border bg-ost-panel/80 px-2 py-1 text-xs text-ost-muted">
            <span>Drop PDF here to add sheets</span>
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setPage(currentPage - 1)}
              className="rounded px-2 py-1 hover:bg-white/10 disabled:opacity-30"
            >
              ◀ Prev
            </button>
            <button
              type="button"
              disabled={!totalPages || currentPage >= totalPages}
              onClick={() => setPage(currentPage + 1)}
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
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-2">
            <CanvasWorkspace pdfData={pdfData} />
          </div>
          <VoiceControls />
          <TakeoffSidekickPanel />
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
