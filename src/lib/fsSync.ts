import {
  ensureProjectLayout,
  verifyWritable,
  writeBlobToDir,
  writeJson,
} from '@/lib/fsProjectAccess';
import { loadFsRootHandle, loadPdfBlob } from '@/lib/indexedProjectDb';
import { buildOstProjectFile } from '@/lib/serializeOst';
import { useProjectStore } from '@/store/projectStore';
import type { ExportRow } from '@/utils/exportTakeoff';

/** Write `project.ost.json` + PDFs under user-picked workspace folder. */
export async function syncProjectToFileSystem(): Promise<boolean> {
  const root = await loadFsRootHandle();
  if (!root || !(await verifyWritable(root))) return false;
  const s = useProjectStore.getState();
  if (!s.projectId) return false;
  const { projectDir, pdfsDir } = await ensureProjectLayout(root, s.projectId);
  const ost = buildOstProjectFile();
  await writeJson(projectDir, 'project.ost.json', ost);
  for (const d of s.documents) {
    const buf = await loadPdfBlob(s.projectId, d.id);
    if (buf) {
      const safe = d.name.replace(/[^\w.-]+/g, '_') || 'sheet.pdf';
      await writeBlobToDir(pdfsDir, safe, new Blob([buf], { type: 'application/pdf' }));
    }
  }
  return true;
}

export async function exportCsvToFileSystem(
  rows: ExportRow[],
  filename: string
): Promise<boolean> {
  const root = await loadFsRootHandle();
  if (!root || !(await verifyWritable(root))) return false;
  const s = useProjectStore.getState();
  if (!s.projectId) return false;
  const { exportsDir } = await ensureProjectLayout(root, s.projectId);
  const text = [
    'page,condition,quantity,unit,markType,assembly,notes,rate,cost',
    ...rows.map((r) =>
      [
        r.page,
        r.condition,
        r.quantity,
        r.unit,
        r.markType,
        r.assembly,
        r.notes,
        r.rate,
        r.cost,
      ]
        .map((c) => {
          const v = String(c ?? '');
          return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
        })
        .join(',')
    ),
  ].join('\n');
  await writeBlobToDir(
    exportsDir,
    filename,
    new Blob([text], { type: 'text/csv' })
  );
  return true;
}
