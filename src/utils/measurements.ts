import type { ResultKind } from '@/types';

export function pxPerFootFromInput(v: number): number {
  return Number.isFinite(v) && v > 0 ? v : 48;
}

export function feetFromPixels(lenPx: number, pxPerFoot: number): number {
  return lenPx / pxPerFoot;
}

export function sqFeetFromPixels(areaPx: number, pxPerFoot: number): number {
  return areaPx / (pxPerFoot * pxPerFoot);
}

export function polygonAreaPx(
  points: { x: number; y: number }[]
): number {
  let a = 0;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    a += points[i].x * points[j].y - points[j].x * points[i].y;
  }
  return Math.abs(a / 2);
}

export function fabricLineLength(line: {
  calcLinePoints(): { x1: number; y1: number; x2: number; y2: number };
}): number {
  const p = line.calcLinePoints();
  return Math.hypot(p.x2 - p.x1, p.y2 - p.y1);
}

export function formatQty(kind: ResultKind, value: number): string {
  switch (kind) {
    case 'linear':
      return `${value.toFixed(1)} LF`;
    case 'area_gross':
    case 'area_net':
    case 'assembly':
      return `${value.toFixed(1)} SF`;
    case 'count':
      return `${Math.round(value)} ct`;
    default:
      return value.toFixed(2);
  }
}
