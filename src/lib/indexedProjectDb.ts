import { get, set, del } from 'idb-keyval';
import type { OstProjectFileV1 } from '@/lib/ostTypes';

const REGISTRY_KEY = 'ost-project-registry';

export interface RegistryEntry {
  id: string;
  name: string;
  updatedAt: number;
}

export async function listRegistry(): Promise<RegistryEntry[]> {
  const raw = await get<RegistryEntry[]>(REGISTRY_KEY);
  return Array.isArray(raw) ? raw.slice().sort((a, b) => b.updatedAt - a.updatedAt) : [];
}

export async function upsertRegistryEntry(entry: RegistryEntry): Promise<void> {
  const list = await listRegistry();
  const i = list.findIndex((x) => x.id === entry.id);
  if (i >= 0) list[i] = entry;
  else list.push(entry);
  await set(REGISTRY_KEY, list);
}

export async function removeRegistryEntry(id: string): Promise<void> {
  const list = (await listRegistry()).filter((x) => x.id !== id);
  await set(REGISTRY_KEY, list);
}

function ostKey(projectId: string) {
  return `ost-json:${projectId}`;
}

function blobKey(projectId: string, docId: string) {
  return `ost-pdf:${projectId}:${docId}`;
}

export async function saveOstProject(
  projectId: string,
  data: OstProjectFileV1
): Promise<void> {
  await set(ostKey(projectId), JSON.stringify(data));
}

export async function loadOstProject(
  projectId: string
): Promise<OstProjectFileV1 | null> {
  const raw = await get<string>(ostKey(projectId));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as OstProjectFileV1;
  } catch {
    return null;
  }
}

export async function savePdfBlob(
  projectId: string,
  docId: string,
  buffer: ArrayBuffer
): Promise<void> {
  await set(blobKey(projectId, docId), buffer);
}

export async function loadPdfBlob(
  projectId: string,
  docId: string
): Promise<ArrayBuffer | undefined> {
  return get<ArrayBuffer>(blobKey(projectId, docId));
}

export async function deleteProjectFromIdb(projectId: string): Promise<void> {
  const ost = await loadOstProject(projectId);
  if (ost?.documents) {
    for (const d of ost.documents) {
      await del(blobKey(projectId, d.id));
    }
  }
  await del(ostKey(projectId));
  await removeRegistryEntry(projectId);
}

const FS_ROOT_KEY = 'ost-fs-root-handle';

/** Persist FileSystemDirectoryHandle (Chrome/Edge) for workspace root. */
export async function saveFsRootHandle(
  handle: FileSystemDirectoryHandle
): Promise<void> {
  await set(FS_ROOT_KEY, handle);
}

export async function loadFsRootHandle(): Promise<FileSystemDirectoryHandle | undefined> {
  return get<FileSystemDirectoryHandle>(FS_ROOT_KEY);
}
