import { fabric } from 'fabric';

export interface SimilarMatch {
  objectNid: string;
  score: number;
}

/**
 * Rough similarity: same fabric type + similar bounding box area (client-side v1).
 */
export function findSimilarMarks(
  canvas: fabric.Canvas,
  target: fabric.Object
): SimilarMatch[] {
  const tType = target.type;
  const tb = target.getBoundingRect(true);
  const tArea = tb.width * tb.height;
  const out: SimilarMatch[] = [];

  for (const o of canvas.getObjects()) {
    if (o === target) continue;
    const nid = (o as fabric.Object & { nid?: string }).nid;
    if (!nid) continue;
    if (o.type !== tType) continue;
    const b = o.getBoundingRect(true);
    const area = b.width * b.height;
    const ratio = Math.min(area, tArea) / Math.max(area, tArea, 1);
    if (ratio > 0.72) {
      out.push({ objectNid: nid, score: ratio });
    }
  }
  return out.sort((a, b) => b.score - a.score);
}
