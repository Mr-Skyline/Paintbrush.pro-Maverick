import type { TextItem } from '@/types';
import type { PDFPageProxy } from 'pdfjs-dist';

export async function extractPageText(
  page: PDFPageProxy,
  pageIndex: number
): Promise<TextItem[]> {
  const tc = await page.getTextContent();
  const viewport = page.getViewport({ scale: 1 });
  const out: TextItem[] = [];

  for (const item of tc.items) {
    if (!('str' in item) || typeof item.str !== 'string') continue;
    const tm = item.transform;
    const x = tm[4];
    const y = viewport.height - tm[5];
    const w = (item as { width?: number }).width ?? Math.abs(tm[0]) * item.str.length * 0.5;
    const h =
      (item as { height?: number }).height ?? (Math.abs(tm[3]) || 12);
    out.push({ str: item.str, x, y, width: w, height: h, pageIndex });
  }
  return out;
}

export function findTextHints(text: TextItem[]): {
  doors: number;
  windows: number;
  act: boolean;
  gwb: boolean;
} {
  const blob = text.map((t) => t.str).join(' ').toLowerCase();
  const doorMatches = blob.match(/\bdoor[s]?\b/g);
  const winMatches = blob.match(/\bwindow[s]?|\bwd\b|\bglazing\b/g);
  return {
    doors: doorMatches?.length ?? 0,
    windows: winMatches?.length ?? 0,
    act: /\bact\b|acoustical|lay-?in|ceiling\s*tile/i.test(blob),
    gwb: /\bgwb\b|gypsum|drywall|sheetrock|5\/8|1\/2/i.test(blob),
  };
}
