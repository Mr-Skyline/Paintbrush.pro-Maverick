/**
 * File System Access API — project layout:
 *   {root}/{projectId}/project.ost.json
 *   {root}/{projectId}/pdfs/{originalName}.pdf
 *   {root}/{projectId}/exports/*.csv
 */

type DirPickerWin = Window &
  typeof globalThis & {
    showDirectoryPicker?: (options: {
      mode: 'readwrite';
    }) => Promise<FileSystemDirectoryHandle>;
  };

export async function pickWorkspaceDirectory(): Promise<FileSystemDirectoryHandle | null> {
  const w = window as DirPickerWin;
  if (typeof w.showDirectoryPicker !== 'function') return null;
  try {
    return await w.showDirectoryPicker({ mode: 'readwrite' });
  } catch {
    return null;
  }
}

export async function ensureProjectLayout(
  root: FileSystemDirectoryHandle,
  projectId: string
) {
  const proj = await root.getDirectoryHandle(projectId, { create: true });
  const pdfs = await proj.getDirectoryHandle('pdfs', { create: true });
  const exports = await proj.getDirectoryHandle('exports', { create: true });
  return { projectDir: proj, pdfsDir: pdfs, exportsDir: exports };
}

export async function writeBlobToDir(
  dir: FileSystemDirectoryHandle,
  fileName: string,
  data: Blob
) {
  const fh = await dir.getFileHandle(fileName, { create: true });
  const w = await fh.createWritable();
  await w.write(data);
  await w.close();
}

export async function writeJson(
  dir: FileSystemDirectoryHandle,
  fileName: string,
  obj: unknown
) {
  await writeBlobToDir(
    dir,
    fileName,
    new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
  );
}

type DirHandlePerm = FileSystemDirectoryHandle & {
  queryPermission?: (o: { mode: 'readwrite' }) => Promise<PermissionState>;
  requestPermission?: (o: { mode: 'readwrite' }) => Promise<PermissionState>;
};

/** Re-request permission if tab was reloaded (best-effort). */
export async function verifyWritable(
  handle: FileSystemDirectoryHandle
): Promise<boolean> {
  try {
    const h = handle as DirHandlePerm;
    const opts = { mode: 'readwrite' as const };
    if (h.queryPermission && (await h.queryPermission(opts)) === 'granted')
      return true;
    if (h.requestPermission) {
      return (await h.requestPermission(opts)) === 'granted';
    }
    return true;
  } catch {
    return false;
  }
}
