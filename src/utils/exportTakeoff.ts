import type { Condition } from '@/types';
import {
  fabricLineLength,
  feetFromPixels,
  polygonAreaPx,
  pxPerFootFromInput,
  sqFeetFromPixels,
} from '@/utils/measurements';
import { fabric } from 'fabric';

declare global {
  interface Window {
    /** SheetJS from index.html CDN */
    XLSX?: {
      utils: {
        book_new: () => unknown;
        json_to_sheet: (data: unknown) => unknown;
        book_append_sheet: (
          wb: unknown,
          ws: unknown,
          name: string
        ) => void;
      };
      writeFile: (wb: unknown, filename: string) => void;
    };
  }
}

export const FABRIC_KEYS = [
  'nid',
  'conditionIds',
  'markType',
  'notes',
  'isBoost',
  'assemblyTag',
  'aiScope',
] as const;

export interface ExportRow {
  page: number;
  condition: string;
  quantity: string;
  unit: string;
  markType: string;
  assembly: string;
  notes: string;
  rate: string;
  cost: string;
}

function polygonAbsPoints(o: fabric.Polygon): { x: number; y: number }[] {
  const po = o.pathOffset || { x: 0, y: 0 };
  return (o.points || []).map((p) => ({
    x: p.x - po.x + (o.left || 0),
    y: p.y - po.y + (o.top || 0),
  }));
}

export function rowsFromCanvasPage(
  canvas: fabric.Canvas,
  pageNum: number,
  conditions: Condition[],
  pxPerFoot: number
): ExportRow[] {
  const byId = Object.fromEntries(conditions.map((c) => [c.id, c]));
  const rows: ExportRow[] = [];

  for (const obj of canvas.getObjects()) {
    const ext = obj as fabric.Object & {
      nid?: string;
      conditionIds?: string[];
      markType?: string;
      notes?: string;
      isBoost?: boolean;
      assemblyTag?: string;
      aiScope?: boolean;
    };
    if (ext.isBoost || ext.aiScope) continue;
    const ids = ext.conditionIds?.length
      ? ext.conditionIds
      : ['_unassigned'];
    for (const cid of ids) {
      const cond = byId[cid];
      const cname = cond?.name ?? 'Unassigned';
      const rk = cond?.resultKind ?? 'linear';
      let qty = '';
      let unit = '';
      if (rk === 'count' || ext.markType === 'count') {
        qty = '1';
        unit = 'count';
      } else if (obj.type === 'line') {
        const len = fabricLineLength(obj as fabric.Line);
        qty = feetFromPixels(len, pxPerFoot).toFixed(2);
        unit = 'LF';
      } else if (obj.type === 'polyline' && 'points' in obj) {
        const pl = obj as fabric.Polyline;
        const pts = pl.points || [];
        let len = 0;
        for (let i = 1; i < pts.length; i++) {
          len += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
        }
        qty = feetFromPixels(len, pxPerFoot).toFixed(2);
        unit = 'LF';
      } else if (obj.type === 'polygon') {
        const pts = polygonAbsPoints(obj as fabric.Polygon);
        if (rk === 'area_gross' || rk === 'area_net' || rk === 'assembly') {
          qty = sqFeetFromPixels(polygonAreaPx(pts), pxPerFoot).toFixed(2);
          unit = 'SF';
        } else {
          let len = 0;
          for (let i = 0; i < pts.length; i++) {
            const j = (i + 1) % pts.length;
            len += Math.hypot(pts[j].x - pts[i].x, pts[j].y - pts[i].y);
          }
          qty = feetFromPixels(len, pxPerFoot).toFixed(2);
          unit = 'LF';
        }
      } else if (obj.type === 'circle' && ext.markType === 'count') {
        qty = '1';
        unit = 'count';
      } else {
        continue;
      }
      const rate = cond?.unitPrice;
      const qn = parseFloat(qty);
      const cost =
        rate != null && Number.isFinite(qn) ? (qn * rate).toFixed(2) : '';
      rows.push({
        page: pageNum,
        condition: cname,
        quantity: qty,
        unit,
        markType: ext.markType ?? obj.type ?? '',
        assembly: ext.assemblyTag ?? '',
        notes: ext.notes ?? '',
        rate: rate != null ? String(rate) : '',
        cost,
      });
    }
  }
  return rows;
}

export function downloadCsv(rows: ExportRow[]) {
  const header = [
    'page',
    'condition',
    'quantity',
    'unit',
    'markType',
    'assembly',
    'notes',
    'rate',
    'cost',
  ];
  const lines = [
    header.join(','),
    ...rows.map((r) =>
      header
        .map((h) => {
          const v = String((r as unknown as Record<string, string>)[h] ?? '');
          return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
        })
        .join(',')
    ),
  ];
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'takeoff-export.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}

export function downloadXlsx(rows: ExportRow[], summary?: Record<string, unknown>[]) {
  const XLSX = window.XLSX;
  if (!XLSX) {
    alert('SheetJS not loaded');
    return;
  }
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), 'Takeoff');
  if (summary?.length) {
    XLSX.utils.book_append_sheet(
      wb,
      XLSX.utils.json_to_sheet(summary),
      'Summary'
    );
  }
  XLSX.writeFile(wb, 'takeoff-export.xlsx');
}

export { pxPerFootFromInput };
