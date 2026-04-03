import type { ExportRow } from '@/utils/exportTakeoff';

/** Columns tuned for Paintbrush import bot (extend as your bot expects). */
export function toPaintbrushCsvLines(rows: ExportRow[]): string[] {
  const header = [
    'page',
    'condition',
    'quantity',
    'unit',
    'mark_type',
    'assembly',
    'notes',
    'rate',
    'cost',
  ];
  const lines = [header.join(',')];
  for (const r of rows) {
    const rec: Record<string, string> = {
      page: String(r.page),
      condition: r.condition,
      quantity: r.quantity,
      unit: r.unit,
      mark_type: r.markType,
      assembly: r.assembly,
      notes: r.notes,
      rate: r.rate,
      cost: r.cost,
    };
    lines.push(
      header
        .map((h) => {
          const v = rec[h] ?? '';
          return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
        })
        .join(',')
    );
  }
  return lines;
}

export function downloadPaintbrushCsv(rows: ExportRow[]) {
  const blob = new Blob([toPaintbrushCsvLines(rows).join('\n')], {
    type: 'text/csv',
  });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'paintbrush-takeoff.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}
