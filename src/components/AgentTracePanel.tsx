'use client';

import { useMemo, useState } from 'react';
import {
  clearAgentTraceEvents,
  downloadAgentTraceJsonl,
  getCurrentAgentTraceSessionId,
  listAgentTraceEvents,
  type AgentTraceCategory,
  type AgentTraceEvent,
} from '@/lib/agentTrace';
import { TraceViewerPanel } from '@/components/TraceViewerPanel';

const CATEGORIES: AgentTraceCategory[] = ['action', 'decision', 'outcome', 'session'];

type ResultBucket = 'success' | 'error' | 'neutral';

const RESULT_KEYS: ResultBucket[] = ['success', 'error', 'neutral'];

function normalizeResultBucket(result: string | undefined): ResultBucket {
  const r = (result ?? '').toLowerCase();
  if (r === 'success' || r === 'ok' || r === 'pass' || r === 'passed') return 'success';
  if (r === 'error' || r === 'failure' || r === 'fail' || r === 'failed') return 'error';
  return 'neutral';
}

function filterEvents(
  events: AgentTraceEvent[],
  catOn: Record<AgentTraceCategory, boolean>,
  resOn: Record<ResultBucket, boolean>,
): AgentTraceEvent[] {
  return events.filter((e) => {
    if (!catOn[e.category]) return false;
    return resOn[normalizeResultBucket(e.result)];
  });
}

function countByCategory(events: AgentTraceEvent[]): Record<AgentTraceCategory, number> {
  const m: Record<AgentTraceCategory, number> = {
    action: 0,
    decision: 0,
    outcome: 0,
    session: 0,
  };
  for (const e of events) {
    m[e.category] += 1;
  }
  return m;
}

function countByResult(events: AgentTraceEvent[]): Record<ResultBucket, number> {
  const m: Record<ResultBucket, number> = { success: 0, error: 0, neutral: 0 };
  for (const e of events) {
    m[normalizeResultBucket(e.result)] += 1;
  }
  return m;
}

const toggleBase =
  'rounded border px-1.5 py-0.5 text-[10px] transition-colors hover:bg-white/10 focus:outline-none focus-visible:ring-1 focus-visible:ring-ost-fg/40';
const toggleOn = 'border-emerald-500/45 bg-emerald-500/15 text-ost-fg';
const toggleOff = 'border-ost-border text-ost-muted opacity-70';

export function AgentTracePanel({
  refreshKey,
  onAfterMutate,
  onReplay,
  onReplayDryRun,
}: {
  refreshKey: number;
  onAfterMutate?: () => void;
  onReplay?: () => void;
  onReplayDryRun?: () => void;
}) {
  void refreshKey;
  const all = listAgentTraceEvents();
  const total = all.length;
  const currentSessionId = getCurrentAgentTraceSessionId();

  const [catOn, setCatOn] = useState<Record<AgentTraceCategory, boolean>>({
    action: true,
    decision: true,
    outcome: true,
    session: true,
  });
  const [resOn, setResOn] = useState<Record<ResultBucket, boolean>>({
    success: true,
    error: true,
    neutral: true,
  });
  const [showMore, setShowMore] = useState(false);

  const filtered = useMemo(() => filterEvents(all, catOn, resOn), [all, catOn, resOn]);
  const filteredTotal = filtered.length;
  const catCounts = useMemo(() => countByCategory(filtered), [filtered]);
  const resCounts = useMemo(() => countByResult(filtered), [filtered]);

  const bump = () => onAfterMutate?.();

  return (
    <div className="border-b border-ost-border bg-ost-panel/90 px-2 py-1.5 text-[11px] text-ost-muted">
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-ost-fg">
          Trace · {filteredTotal} of {total} events
        </span>
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
        {onReplayDryRun ? (
          <button
            type="button"
            className="rounded border border-ost-border px-1.5 py-0.5 hover:bg-white/10"
            onClick={() => {
              onReplayDryRun();
              bump();
            }}
          >
            Replay dry-run
          </button>
        ) : null}
      </div>

      <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="shrink-0 text-[10px] uppercase tracking-wide text-ost-muted">Cat</span>
        <div className="flex flex-wrap gap-1">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              type="button"
              aria-pressed={catOn[c]}
              className={`${toggleBase} ${catOn[c] ? toggleOn : toggleOff}`}
              onClick={() => setCatOn((s) => ({ ...s, [c]: !s[c] }))}
            >
              {c}{' '}
              <span className="font-mono tabular-nums text-ost-fg/90">({catCounts[c]})</span>
            </button>
          ))}
        </div>
        <span className="hidden h-3 w-px bg-ost-border sm:inline" aria-hidden />
        <span className="shrink-0 text-[10px] uppercase tracking-wide text-ost-muted">Result</span>
        <div className="flex flex-wrap gap-1">
          {RESULT_KEYS.map((r) => {
            const label = r === 'success' ? 'ok' : r === 'error' ? 'err' : 'neu';
            return (
              <button
                key={r}
                type="button"
                aria-pressed={resOn[r]}
                className={`${toggleBase} ${resOn[r] ? toggleOn : toggleOff}`}
                onClick={() => setResOn((s) => ({ ...s, [r]: !s[r] }))}
              >
                {label}{' '}
                <span className="font-mono tabular-nums text-ost-fg/90">({resCounts[r]})</span>
              </button>
            );
          })}
        </div>
        <button
          type="button"
          aria-pressed={showMore}
          className={`${toggleBase} ml-auto sm:ml-0 ${showMore ? toggleOn : toggleOff}`}
          onClick={() => setShowMore((v) => !v)}
        >
          {showMore ? 'Show less' : 'Show more'}
        </button>
      </div>

      <div className="mb-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px]">
        {total === 0 ? (
          <span>No category counts</span>
        ) : (
          CATEGORIES.map((c) => (
            <span key={c}>
              {c}: <span className="text-ost-fg">{catCounts[c]}</span>
            </span>
          ))
        )}
        {total > 0 ? (
          <>
            <span className="text-ost-border">·</span>
            <span>
              ok <span className="text-emerald-400/90">{resCounts.success}</span>
            </span>
            <span>
              err <span className="text-rose-400/90">{resCounts.error}</span>
            </span>
            <span>
              neu <span className="text-slate-400">{resCounts.neutral}</span>
            </span>
          </>
        ) : null}
      </div>

      <TraceViewerPanel
        events={filtered}
        maxRows={showMore ? 60 : 20}
        title="Recent trace events"
      />
    </div>
  );
}
