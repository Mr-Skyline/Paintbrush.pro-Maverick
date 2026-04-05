import {
  clearAgentTraceEvents,
  downloadAgentTraceJsonl,
  listAgentTraceEvents,
  type AgentTraceEvent,
} from '@/lib/agentTrace';

function fmtTime(ts: number): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return String(ts);
  }
}

function contextSnippet(ctx: Record<string, unknown> | undefined, maxLen = 140): string {
  if (ctx === undefined || Object.keys(ctx).length === 0) return '—';
  try {
    const s = JSON.stringify(ctx);
    if (s.length <= maxLen) return s;
    return `${s.slice(0, maxLen - 1)}…`;
  } catch {
    return '(context)';
  }
}

export function AgentTracePanel({
  refreshKey,
  onAfterMutate,
  onReplay,
}: {
  refreshKey: number;
  onAfterMutate?: () => void;
  onReplay?: () => void;
}) {
  void refreshKey;
  const all = listAgentTraceEvents();
  const total = all.length;
  const byCategory: Record<string, number> = {};
  for (const e of all) {
    byCategory[e.category] = (byCategory[e.category] ?? 0) + 1;
  }
  const topCategories = Object.entries(byCategory)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 6);
  const recent = [...all].reverse().slice(0, 20);

  const bump = () => onAfterMutate?.();

  return (
    <div className="border-b border-ost-border bg-ost-panel/90 px-2 py-1.5 text-[11px] text-ost-muted">
      <div className="mb-1 flex flex-wrap items-center gap-1">
        <span className="font-medium text-ost-fg">Trace · {total} events</span>
        <button
          type="button"
          className="rounded border border-ost-border px-1.5 py-0.5 hover:bg-white/10"
          onClick={bump}
        >
          Refresh
        </button>
        <button
          type="button"
          className="rounded border border-ost-border px-1.5 py-0.5 hover:bg-white/10"
          onClick={() => {
            downloadAgentTraceJsonl();
            bump();
          }}
        >
          Export JSONL
        </button>
        <button
          type="button"
          className="rounded border border-ost-border px-1.5 py-0.5 hover:bg-white/10"
          onClick={() => {
            clearAgentTraceEvents();
            bump();
          }}
        >
          Clear
        </button>
        {onReplay ? (
          <button
            type="button"
            className="rounded border border-ost-border px-1.5 py-0.5 hover:bg-white/10"
            onClick={() => {
              onReplay();
              bump();
            }}
          >
            Replay
          </button>
        ) : null}
      </div>
      <div className="mb-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px]">
        {topCategories.length === 0 ? (
          <span>No category counts</span>
        ) : (
          topCategories.map(([cat, n]) => (
            <span key={cat}>
              {cat}: <span className="text-ost-fg">{n}</span>
            </span>
          ))
        )}
      </div>
      <ul className="max-h-[11rem] space-y-1 overflow-y-auto font-mono text-[10px] leading-tight">
        {recent.length === 0 ? (
          <li className="text-ost-muted">No trace events yet.</li>
        ) : (
          recent.map((ev: AgentTraceEvent) => (
            <li key={ev.id} className="border-b border-ost-border/40 pb-1 last:border-0">
              <div className="text-ost-fg">
                {fmtTime(ev.ts)} · <span className="text-slate-300">{ev.event}</span> ·{' '}
                {ev.result ?? '—'}
              </div>
              <div className="mt-0.5 break-all text-[9px] text-ost-muted/90">
                {contextSnippet(ev.context)}
              </div>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
