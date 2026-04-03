import {
  loadOstProject,
  loadPdfBlob,
  saveOstProject,
  savePdfBlob,
  upsertRegistryEntry,
} from '@/lib/indexedProjectDb';
import { applyOstProjectFile, buildOstProjectFile } from '@/lib/serializeOst';
import { useProjectStore } from '@/store/projectStore';

export async function saveProjectToIndexedDb(): Promise<void> {
  const ost = buildOstProjectFile();
  if (!ost.projectId?.trim()) throw new Error('No project id');
  await saveOstProject(ost.projectId, ost);
  await upsertRegistryEntry({
    id: ost.projectId,
    name: ost.projectName || 'Untitled',
    updatedAt: ost.updatedAt,
  });
}

/** Save a PDF sheet into the current project (IndexedDB). */
export async function savePdfToCurrentProject(
  docId: string,
  _fileName: string,
  buffer: ArrayBuffer
): Promise<void> {
  const pid = useProjectStore.getState().projectId;
  if (!pid) throw new Error('No project');
  await savePdfBlob(pid, docId, buffer);
}

export async function loadProjectFromIndexedDb(projectId: string): Promise<void> {
  const ost = await loadOstProject(projectId);
  if (!ost) throw new Error('Project not found');
  applyOstProjectFile(ost);
}

export async function getPdfBufferForActiveOrDoc(
  projectId: string,
  docId: string
): Promise<ArrayBuffer | undefined> {
  return loadPdfBlob(projectId, docId);
}
