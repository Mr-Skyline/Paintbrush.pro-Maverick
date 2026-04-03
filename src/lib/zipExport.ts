import type { OstProjectFileV1 } from '@/lib/ostTypes';
import JSZip from 'jszip';

/** Fallback when File System Access API is unavailable: zip `projects/{id}/...` layout. */
export async function downloadProjectZip(
  projectId: string,
  projectName: string,
  ost: OstProjectFileV1,
  pdfParts: { relativePath: string; buffer: ArrayBuffer }[]
): Promise<void> {
  const zip = new JSZip();
  const root = `projects/${projectId}`;
  zip.file(`${root}/project.ost.json`, JSON.stringify(ost, null, 2));
  for (const p of pdfParts) {
    zip.file(`${root}/${p.relativePath}`, p.buffer);
  }
  const blob = await zip.generateAsync({ type: 'blob' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${projectName.replace(/\W+/g, '-') || 'takeoff'}-export.zip`;
  a.click();
  URL.revokeObjectURL(a.href);
}
