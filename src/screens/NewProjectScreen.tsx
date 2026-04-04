import { savePdfBlob, upsertRegistryEntry } from '@/lib/indexedProjectDb';
import { useNavigationStore } from '@/store/navigationStore';
import { useProjectStore } from '@/store/projectStore';
import { openPdfFromArrayBuffer } from '@/utils/openPdfFromArrayBuffer';
import { useCallback, useState } from 'react';

export function NewProjectScreen() {
  const [busy, setBusy] = useState(false);
  const goProjects = useNavigationStore((s) => s.goToProjects);
  const openWorkspace = useNavigationStore((s) => s.openWorkspace);

  const ingestFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = [...files].filter((f) => /\.pdf$/i.test(f.name));
      if (!list.length) {
        alert('Add at least one PDF.');
        return;
      }
      const name =
        window.prompt('Project name', list[0].name.replace(/\.pdf$/i, '')) ||
        'Untitled job';
      setBusy(true);
      try {
        const projectId = useProjectStore
          .getState()
          .resetWorkspaceForNewProject(name);
        for (const file of list) {
          const buf = await file.arrayBuffer();
          const docId = crypto.randomUUID();
          await savePdfBlob(projectId, docId, buf);
          const doc = await openPdfFromArrayBuffer(buf);
          useProjectStore
            .getState()
            .addPdfDocument(docId, file.name, doc.numPages);
        }
        await upsertRegistryEntry({
          id: projectId,
          name,
          updatedAt: Date.now(),
        });
        openWorkspace(projectId);
      } finally {
        setBusy(false);
      }
    },
    [openWorkspace]
  );

  return (
    <div className="flex min-h-full flex-col items-center justify-center bg-ost-bg p-6 text-center text-slate-100">
      <button
        type="button"
        onClick={goProjects}
        className="mb-6 self-start text-sm text-ost-muted hover:text-white"
      >
        ← Back to projects
      </button>
      <h1 className="text-2xl font-bold text-white">New project</h1>
      <p className="mt-2 max-w-md text-sm text-ost-muted">
        Drop a full plan set (multiple PDFs). Files are copied into browser
        storage under{' '}
        <code className="rounded bg-black/40 px-1">projects/&#123;id&#125;/pdfs/</code>.
      </p>

      <label
        className="mt-10 flex w-full max-w-xl cursor-pointer flex-col items-center rounded-2xl border-2 border-dashed border-blue-500/40 bg-ost-panel/80 px-8 py-20 transition hover:border-blue-400/60 hover:bg-ost-panel"
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (e.dataTransfer.files?.length) void ingestFiles(e.dataTransfer.files);
        }}
      >
        <input
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          disabled={busy}
          onChange={(e) => {
            const fl = e.target.files;
            if (fl?.length) void ingestFiles(fl);
          }}
        />
        <span className="text-lg font-medium text-blue-200">
          {busy ? 'Working…' : 'Drag & drop PDFs here'}
        </span>
        <span className="mt-2 text-sm text-ost-muted">or click to browse</span>
      </label>
    </div>
  );
}
