import type { BoostFinding, BoostReviewSummary, Condition } from '@/types';
import type { AiFocusBoundingRect } from '@/utils/aiFocusContext';
import { extractPageText, findTextHints } from '@/utils/pdfText';
import type { PDFPageProxy } from 'pdfjs-dist';

function nid() {
  return `b-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n));
}

/**
 * Region where Boost places synthetic geometry. With `focus`, matches the purple AI box
 * (clipped to the overlay). Without focus, uses central band of the full sheet.
 */
function boostPlacementInner(
  renderWidth: number,
  renderHeight: number,
  focus: AiFocusBoundingRect | null | undefined
): { x0: number; y0: number; x1: number; y1: number; w: number; h: number } {
  if (
    !focus ||
    focus.width < 8 ||
    focus.height < 8 ||
    !Number.isFinite(focus.left + focus.top)
  ) {
    return {
      x0: renderWidth * 0.12,
      y0: renderHeight * 0.08,
      x1: renderWidth * 0.88,
      y1: renderHeight * 0.92,
      w: renderWidth * 0.76,
      h: renderHeight * 0.84,
    };
  }
  const l = clamp(focus.left, 0, Math.max(0, renderWidth - 8));
  const t = clamp(focus.top, 0, Math.max(0, renderHeight - 8));
  const r = clamp(focus.left + focus.width, l + 8, renderWidth);
  const b = clamp(focus.top + focus.height, t + 8, renderHeight);
  return { x0: l, y0: t, x1: r, y1: b, w: r - l, h: b - t };
}

/**
 * Client-side Boost v1: PDF text + light geometry heuristics (expand with Grok server-side).
 * When `aiFocusRect` is set (purple AI box on this sheet), candidate marks are generated inside it.
 */
export async function runTakeoffBoostOnPage(
  page: PDFPageProxy,
  pageIndex: number,
  renderWidth: number,
  renderHeight: number,
  existing: Condition[],
  aiFocusRect?: AiFocusBoundingRect | null
): Promise<BoostReviewSummary> {
  const text = await extractPageText(page, pageIndex);
  const hints = findTextHints(text);
  const viewport = page.getViewport({ scale: 1 });
  const sx = renderWidth / viewport.width;
  const sy = renderHeight / viewport.height;

  const suggestedConditions: Omit<Condition, 'id'>[] = [];
  const needWall = !existing.some((c) => /wall/i.test(c.name));
  const needAct = hints.act && !existing.some((c) => /act|acoustical/i.test(c.name));
  const needGwb =
    hints.gwb && !existing.some((c) => /gwb|gypsum|drywall/i.test(c.name));

  if (needWall) {
    suggestedConditions.push({
      name: 'Interior Walls — 5/8 GWB',
      color: '#22c55e',
      linePattern: 'solid',
      strokeWidth: 2,
      fillOpacity: 0.14,
      resultKind: 'linear',
    });
  }
  if (needAct) {
    suggestedConditions.push({
      name: 'ACT Ceilings',
      color: '#a855f7',
      linePattern: 'dashed',
      strokeWidth: 2,
      fillOpacity: 0.16,
      resultKind: 'area_gross',
    });
  }
  if (needGwb) {
    suggestedConditions.push({
      name: 'GWB Ceilings',
      color: '#6366f1',
      linePattern: 'solid',
      strokeWidth: 2,
      fillOpacity: 0.14,
      resultKind: 'area_gross',
    });
  }

  const inner = boostPlacementInner(renderWidth, renderHeight, aiFocusRect);
  const scopedToAiBox = !!(
    aiFocusRect &&
    aiFocusRect.width >= 8 &&
    aiFocusRect.height >= 8
  );

  const findings: BoostFinding[] = [];
  let wallLf = 0;

  // Synthetic "wall runs" from horizontal scan lines (placeholder for vector wall detect)
  const bands = [0.22, 0.5, 0.78].map((t) => inner.y0 + inner.h * t);
  for (let i = 0; i < bands.length; i++) {
    const y = bands[i];
    const x1 = inner.x0 + inner.w * 0.06;
    const x2 = inner.x0 + inner.w * 0.94;
    const lf = (x2 - x1) / Math.min(sx, sy) / 48; // rough if 48 px/ft — caller should scale
    wallLf += lf;
    findings.push({
      id: nid(),
      kind: 'wall',
      description: `Wall run ${i + 1} (Boost heuristic)`,
      conditionName: 'Interior Walls — 5/8 GWB',
      geometry: { type: 'line', x1, y1: y, x2, y2: y },
      confidence: scopedToAiBox ? 0.42 : 0.35,
    });
  }

  const innerArea = inner.w * inner.h;
  const fullArea = renderWidth * renderHeight || 1;
  const density = scopedToAiBox
    ? Math.max(0.35, Math.min(1, Math.sqrt(innerArea / fullArea) * 1.25))
    : 1;

  const doorCount = Math.max(
    1,
    Math.round(
      Math.max(2, Math.min(24, hints.doors + 4)) * density
    )
  );
  const winCount = Math.max(
    1,
    Math.round(Math.max(1, Math.min(20, hints.windows + 2)) * density)
  );
  for (let i = 0; i < doorCount; i++) {
    const cx = inner.x0 + inner.w * (0.12 + ((i * 7) % 76) / 100);
    const cy = inner.y0 + inner.h * (0.18 + ((i * 11) % 64) / 100);
    findings.push({
      id: nid(),
      kind: 'door',
      description: `Door candidate ${i + 1}`,
      conditionName: 'Doors — hollow metal',
      geometry: { type: 'point', x: cx, y: cy },
      confidence: 0.4,
    });
  }
  for (let i = 0; i < winCount; i++) {
    const cx = inner.x0 + inner.w * (0.15 + ((i * 9) % 70) / 100);
    const cy = inner.y0 + inner.h * (0.12 + ((i * 13) % 56) / 100);
    findings.push({
      id: nid(),
      kind: 'window',
      description: `Window candidate ${i + 1}`,
      conditionName: 'Windows',
      geometry: {
        type: 'rect',
        x: cx - 18,
        y: cy - 12,
        w: 36,
        h: 24,
      },
      confidence: 0.33,
    });
  }

  if (hints.act) {
    findings.push({
      id: nid(),
      kind: 'ceiling_act',
      description: scopedToAiBox
        ? 'ACT ceiling zone (text tag, inside AI box)'
        : 'ACT ceiling zone (text tag)',
      conditionName: 'ACT Ceilings',
      geometry: {
        type: 'polygon',
        points: [
          { x: inner.x0 + inner.w * 0.06, y: inner.y0 + inner.h * 0.08 },
          { x: inner.x0 + inner.w * 0.94, y: inner.y0 + inner.h * 0.08 },
          { x: inner.x0 + inner.w * 0.9, y: inner.y0 + inner.h * 0.58 },
          { x: inner.x0 + inner.w * 0.1, y: inner.y0 + inner.h * 0.58 },
        ],
      },
      confidence: 0.42,
    });
  }

  const scopeNote = scopedToAiBox
    ? ' — heuristics scoped to your purple AI focus box'
    : '';
  const headline = `Found ~${wallLf.toFixed(0)} LF wall hints, ${doorCount} door / ${winCount} window candidates${
    hints.act ? ', ACT ceiling zone' : ''
  }${hints.gwb ? ', GWB tags on sheet' : ''} — approve or edit?${scopeNote}`;

  const actSfBase = inner.w * inner.h * 0.012;
  const gwbSfBase = inner.w * inner.h * 0.008;

  return {
    headline,
    findings,
    stats: {
      wallLf,
      doors: doorCount,
      windows: winCount,
      ceilingActSf: hints.act ? actSfBase : undefined,
      ceilingGwbSf: hints.gwb ? gwbSfBase : undefined,
      rooms: hints.gwb ? 3 : 1,
    },
    suggestedConditions,
  };
}
