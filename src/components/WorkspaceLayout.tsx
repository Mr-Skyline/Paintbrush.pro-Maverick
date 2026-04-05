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
import { useNavigationStore } from '@/store/navigationStore';
import { useProjectStore } from '@/store/projectStore';
import { getAiFocusBoundingRectPx } from '@/utils/aiFocusContext';
import { runTakeoffBoostOnPage } from '@/utils/takeoffBoost';
import { findSimilarMarks } from '@/utils/findSimilar';
import type { ExportRow } from '@/utils/exportTakeoff';
import { fabric } from 'fabric';
import { openPdfFromArrayBuffer } from '@/utils/openPdfFromArrayBuffer';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

type BoostRunResult = { ok: boolean; error?: string; headline?: string };
type WorkflowStepState = 'pending' | 'active' | 'complete';

export function WorkspaceLayout() {
  const [pdfData, setPdfData] = useState<ArrayBuffer | null>(null);
  const [boostOpen, setBoostOpen] = useState(false);
  const [uploadingSheets, setUploadingSheets] = useState(false);
  const [boostRunning, setBoostRunning] = useState(false);
  const [guideMessage, setGuideMessage] = useState<{
    tone: 'neutral' | 'success' | 'error';
    text: string;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const openProjectId = useNavigationStore((s) => s.openProjectId);
  const goProjects = useNavigationStore((s) => s.goToProjects);
  const activeDocumentId = useProjectStore((s) => s.activeDocumentId);
  const currentPage = useProjectStore((s) => s.currentPage);
  const conditions = useProjectStore((s) => s.conditions);
  const setBoostReview = useProjectStore((s) => s.setBoostReview);
  const totalPages = useProjectStore((s) => s.totalPages);
  const projectId = useProjectStore((s) => s.projectId);
  const documents = useProjectStore((s) => s.documents);
  const boostReview = useProjectStore((s) => s.boostReview);
  const reviewOpen = useProjectStore((s) => s.reviewOpen);
  const projectName = useProjectStore((s) => s.projectName);

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

  const fitCanvasView = useCallback(() => {
    const c = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
      .__takeoffCanvas;
    c?.setViewportTransform([1, 0, 0, 1, 0, 0]);
    const pc = document.querySelector('.pdf-canvas') as HTMLElement | null;
    if (pc) pc.style.transform = '';
    c?.requestRenderAll();
  }, []);

  const openPlanPicker = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  useEffect(() => {
    const onOpenPicker = () => openPlanPicker();
    window.addEventListener('takeoff:open-upload-picker', onOpenPicker);
    return () =>
      window.removeEventListener('takeoff:open-upload-picker', onOpenPicker);
  }, [openPlanPicker]);

  const ingestPdfFiles = useCallback(
    async (files: FileList | File[]) => {
      if (!projectId) {
        alert('Open or create a project first.');
        return;
      }
      const pdfs = [...files].filter((f) => /\.pdf$/i.test(f.name));
      if (!pdfs.length) {
        alert('Please select one or more PDF plans.');
        return;
      }
      setUploadingSheets(true);
      setGuideMessage({ tone: 'neutral', text: 'Uploading plans…' });
      try {
        let added = 0;
        for (const file of pdfs) {
          const buf = await file.arrayBuffer();
          const docId = crypto.randomUUID();
          await savePdfBlob(projectId, docId, buf);
          const doc = await openPdfFromArrayBuffer(buf);
          useProjectStore.getState().addPdfDocument(docId, file.name, doc.numPages);
          added += 1;
        }
        await saveProjectToIndexedDb();
        setGuideMessage({
          tone: 'success',
          text: `Added ${added} plan${added === 1 ? '' : 's'}. Next: choose a sheet and run AI takeoff.`,
        });
      } catch (err) {
        console.error(err);
        setGuideMessage({
          tone: 'error',
          text: `Could not add plans: ${String(err)}`,
        });
      } finally {
        setUploadingSheets(false);
      }
    },
    [projectId]
  );

  const runGuidedBoost = useCallback(async () => {
    if (!documents.length) {
      setGuideMessage({ tone: 'error', text: 'Upload plans before running AI.' });
      return;
    }
    setBoostRunning(true);
    setGuideMessage({ tone: 'neutral', text: 'Running AI takeoff on current sheet…' });
    const result = await runBoost('page');
    if (result.ok) {
      setGuideMessage({
        tone: 'success',
        text:
          result.headline ??
          'AI takeoff finished. Review and approve suggestions below.',
      });
      return;
    }
    setGuideMessage({
      tone: 'error',
      text: result.error ?? 'AI takeoff failed.',
    });
    setBoostRunning(false);
  }, [documents.length, runBoost]);

  useEffect(() => {
    if (!boostRunning) return;
    setBoostRunning(false);
  }, [boostReview, boostRunning]);

  const workflowSteps = useMemo(
    () =>
      [
        {
          id: 'upload',
          label: 'Upload plans',
          detail: documents.length
            ? `${documents.length} PDF plan${documents.length === 1 ? '' : 's'} added`
            : 'Add one or more PDF drawings',
          state: documents.length ? 'complete' : 'active',
        },
        {
          id: 'sheet',
          label: 'Choose sheet',
          detail:
            documents.length && totalPages
              ? `Sheet ${currentPage} of ${totalPages}`
              : 'Pick a plan first',
          state: documents.length ? 'complete' : 'pending',
        },
        {
          id: 'run',
          label: 'Run AI takeoff',
          detail: boostReview
            ? `${boostReview.findings.length} findings detected`
            : 'Run AI on current sheet',
          state: boostReview ? 'complete' : documents.length ? 'active' : 'pending',
        },
        {
          id: 'review',
          label: 'Review + apply',
          detail: boostReview
            ? reviewOpen
              ? 'Review panel open below'
              : 'Review panel completed/dismissed'
            : 'Approve and draw suggested marks',
          state: boostReview ? (reviewOpen ? 'active' : 'complete') : 'pending',
        },
      ] satisfies Array<{
        id: string;
        label: string;
        detail: string;
        state: WorkflowStepState;
      }>,
    [boostReview, currentPage, documents.length, reviewOpen, totalPages]
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
    if (!e.dataTransfer.files?.length) return;
    await ingestPdfFiles(e.dataTransfer.files);
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
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDropPdf}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = e.target.files;
          if (files?.length) void ingestPdfFiles(files);
          e.currentTarget.value = '';
        }}
      />
      <ToolbarOST
        onProjects={goProjects}
        onOpenUpload={openPlanPicker}
        onOpenBoost={() => setBoostOpen(true)}
        onFindSimilar={findSimilar}
        onFitView={fitCanvasView}
        onSaveProject={saveManual}
        onSyncDisk={syncDisk}
        onExportPaintbrush={exportPb}
        onDownloadZip={downloadZip}
      />
      <div className="flex min-h-0 flex-1">
        <SidebarLeft />
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="border-b border-ost-border bg-gradient-to-b from-[#111723] to-[#0f141d] px-3 py-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-[320px]">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-ost-muted">
                  Guided takeoff workflow
                </p>
                <h2 className="mt-1 text-base font-semibold text-slate-100">
                  {projectName || 'Untitled project'} · Sheet {totalPages ? currentPage : '—'} /{' '}
                  {totalPages || '—'}
                </h2>
                <ol className="mt-2 grid gap-1.5 md:grid-cols-2">
                  {workflowSteps.map((step, idx) => (
                    <li
                      key={step.id}
                      className={`rounded-md border px-2 py-1.5 ${
                        step.state === 'complete'
                          ? 'border-emerald-700/50 bg-emerald-950/30 text-emerald-200'
                          : step.state === 'active'
                            ? 'border-blue-700/50 bg-blue-950/30 text-blue-200'
                            : 'border-ost-border bg-black/20 text-ost-muted'
                      }`}
                    >
                      <div className="font-medium">
                        {idx + 1}. {step.label}
                      </div>
                      <div className="text-[11px]">{step.detail}</div>
                    </li>
                  ))}
                </ol>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={openPlanPicker}
                  disabled={uploadingSheets}
                  className="rounded-md border border-blue-500/40 bg-blue-600/15 px-3 py-2 text-xs font-medium text-blue-100 hover:bg-blue-600/25 disabled:opacity-50"
                >
                  {uploadingSheets ? 'Uploading plans…' : 'Upload plans (PDF)'}
                </button>
                <button
                  type="button"
                  onClick={() => void runGuidedBoost()}
                  disabled={!documents.length || boostRunning}
                  className="rounded-md bg-emerald-700 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-600 disabled:opacity-40"
                >
                  {boostRunning ? 'AI running…' : 'Run AI takeoff now'}
                </button>
                <button
                  type="button"
                  onClick={() => setBoostOpen(true)}
                  disabled={!documents.length}
                  className="rounded-md border border-ost-border px-3 py-2 text-xs text-ost-muted hover:bg-white/10 disabled:opacity-40"
                >
                  Configure AI
                </button>
              </div>
            </div>
            {guideMessage && (
              <p
                className={`mt-2 ${
                  guideMessage.tone === 'success'
                    ? 'text-emerald-300'
                    : guideMessage.tone === 'error'
                      ? 'text-rose-300'
                      : 'text-ost-muted'
                }`}
              >
                {guideMessage.text}
              </p>
            )}
            {boostReview && (
              <p className="mt-1 text-ost-muted">
                Latest AI result: <span className="text-slate-200">{boostReview.headline}</span>{' '}
                ({boostReview.findings.length} findings,{' '}
                {boostReview.suggestedConditions.length} suggested conditions)
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 border-b border-ost-border bg-ost-panel/70 px-3 py-2 text-xs text-ost-muted">
            <span className="rounded-full border border-ost-border/70 bg-black/20 px-2 py-0.5">
              Tip: drag &amp; drop PDFs anywhere in this workspace to append sheets
            </span>
            <span className="rounded-full border border-ost-border/70 bg-black/20 px-2 py-0.5">
              Use AI box tool to scope AI takeoff region
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-auto bg-[#0b1018] p-3">
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
