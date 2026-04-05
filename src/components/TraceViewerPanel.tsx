export type TraceViewerEvent = {
  id: string;
  ts: string | number;
  category: string;
  event: string;
  result?: string;
  reason?: string;
  context?: Record<string, unknown>;
  sessionId?: string;
};

/** Safe JSON preview for context; empty string when nothing to show. */
export function safeContextPreview(
  context: Record<string, unknown> | undefined,
  maxLen = 120,
): string {
  if (context === undefined || Object.keys(context).length === 0) return '';
  try {
    const s = JSON.stringify(context);
    if (s.length <= maxLen) return s;
    return `${s.slice(0, maxLen - 3)}...`;
  } catch {
    return '(context)';
  }
}

function normalizeResultBucket(result: string | undefined): 'success' | 'error' | 'neutral' {
  const r = (result ?? '').toLowerCase();
  if (r === 'success' || r === 'ok' || r === 'pass' || r === 'passed') return 'success';
  if (r === 'error' || r === 'failure' || r === 'fail' || r === 'failed') return 'error';
  return 'neutral';
}

function formatTime(ts: string | number): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function shortenSessionId(id: string | undefined, max = 8): string {
  if (!id) return '-';
  if (id.length <= max) return id;
  return `${id.slice(0, max)}...`;
}

function truncateReason(s: string | undefined, max = 48): string {
  if (!s) return '-';
  if (s.length <= max) return s;
  return `${s.slice(0, max - 3)}...`;
}

export function TraceViewerPanel({
  events,
  maxRows = 20,
  title = 'Trace viewer',
}: {
  events: TraceViewerEvent[];
  maxRows?: number;
  title?: string;
}) {
  const total = events.length;
  const byCategory: Record<string, number> = {};
  const byResult = { success: 0, error: 0, neutral: 0 };

  for (const e of events) {
    byCategory[e.category] = (byCategory[e.category] ?? 0) + 1;
    byResult[normalizeResultBucket(e.result)] += 1;
  }

  const categoryEntries = Object.entries(byCategory).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

  const sorted = [...events].sort((a, b) => {
    const ta = new Date(a.ts).getTime();
    const tb = new Date(b.ts).getTime();
    const na = Number.isNaN(ta) ? 0 : ta;
    const nb = Number.isNaN(tb) ? 0 : tb;
    return nb - na;
  });
  const rows = sorted.slice(0, maxRows);

  return (
    <div className="rounded border border-ost-border bg-ost-panel/90 text-[11px] text-ost-muted">
      <div className="border-b border-ost-border px-2 py-1.5">
        <h3 className="text-xs font-medium text-ost-fg">{title}</h3>
      </div>

      {total === 0 ? (
        <div className="px-2 py-4 text-center text-[11px] text-ost-muted">No trace events yet.</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-1 border-b border-ost-border p-2 sm:grid-cols-4">
            <div className="rounded border border-ost-border/80 bg-black/20 px-2 py-1">
              <div className="text-[9px] uppercase tracking-wide text-ost-muted">Total</div>
              <div className="font-mono text-sm text-ost-fg">{total}</div>
            </div>
            <div className="rounded border border-ost-border/80 bg-black/20 px-2 py-1 sm:col-span-1">
              <div className="text-[9px] uppercase tracking-wide text-ost-muted">By result</div>
              <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 font-mono text-[10px]">
                <span>
                  ok <span className="text-emerald-400/90">{byResult.success}</span>
                </span>
                <span>
                  err <span className="text-rose-400/90">{byResult.error}</span>
                </span>
                <span>
                  neu <span className="text-slate-400">{byResult.neutral}</span>
                </span>
              </div>
            </div>
            <div className="col-span-2 rounded border border-ost-border/80 bg-black/20 px-2 py-1 sm:col-span-2">
              <div className="text-[9px] uppercase tracking-wide text-ost-muted">By category</div>
              <div className="mt-0.5 flex max-h-14 flex-wrap gap-x-3 gap-y-0.5 overflow-y-auto font-mono text-[10px] leading-tight">
                {categoryEntries.length === 0 ? (
                  <span>-</span>
                ) : (
                  categoryEntries.map(([cat, n]) => (
                    <span key={cat}>
                      {cat}: <span className="text-ost-fg">{n}</span>
                    </span>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="max-h-[14rem] overflow-auto">
            <table className="w-full border-collapse font-mono text-[10px] leading-tight">
              <thead className="sticky top-0 z-[1] bg-ost-panel/95 backdrop-blur-sm">
                <tr className="border-b border-ost-border text-left text-[9px] uppercase tracking-wide text-ost-muted">
                  <th className="px-2 py-1 font-normal">Time</th>
                  <th className="px-2 py-1 font-normal">Category</th>
                  <th className="px-2 py-1 font-normal">Event</th>
                  <th className="px-2 py-1 font-normal">Result</th>
                  <th className="px-2 py-1 font-normal">Reason</th>
                  <th className="px-2 py-1 font-normal">Session</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => {
                  const preview = safeContextPreview(e.context);
                  return (
                    <tr
                      key={e.id}
                      className="border-b border-ost-border/40 align-top hover:bg-white/5"
                      title={preview || undefined}
                    >
                      <td className="whitespace-nowrap px-2 py-1 text-ost-fg">{formatTime(e.ts)}</td>
                      <td className="px-2 py-1 text-slate-300">{e.category}</td>
                      <td className="max-w-[8rem] truncate px-2 py-1 text-slate-200" title={e.event}>
                        {e.event}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1 text-slate-300">{e.result ?? '-'}</td>
                      <td className="max-w-[10rem] truncate px-2 py-1 text-ost-muted" title={e.reason}>
                        {truncateReason(e.reason)}
                      </td>
                      <td className="whitespace-nowrap px-2 py-1 text-ost-muted" title={e.sessionId}>
                        {shortenSessionId(e.sessionId)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
