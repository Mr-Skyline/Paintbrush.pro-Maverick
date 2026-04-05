import {
  clearAgentTraceEvents,
  downloadAgentTraceJsonl,
  getCurrentAgentTraceSessionId,
  listAgentTraceEvents,
} from '@/lib/agentTrace';
import { TraceViewerPanel } from '@/components/TraceViewerPanel';

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
  const currentSessionId = getCurrentAgentTraceSessionId();
  const byCategory: Record<string, number> = {};
  for (const e of all) {
    byCategory[e.category] = (byCategory[e.category] ?? 0) + 1;
  }
  const topCategories = Object.entries(byCategory)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 6);
  const bump = () => onAfterMutate?.();

  return (
    <div className="border-b border-ost-border bg-ost-panel/90 px-2 py-1.5 text-[11px] text-ost-muted">
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-ost-fg">Trace · {total} events</span>
        <span className="rounded border border-ost-border px-1.5 py-0.5 text-[10px]">
          session: {currentSessionId ? `${currentSessionId.slice(0, 12)}...` : 'none'}
        </span>
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
      <TraceViewerPanel
        events={all}
        maxRows={20}
        title="Recent trace events"
      />
    </div>
  );
}
