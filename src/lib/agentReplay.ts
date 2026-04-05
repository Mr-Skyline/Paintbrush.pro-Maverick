/**
 * Deterministic replay of high-confidence trace steps. Pure utilities (no UI imports).
 */

import type { AgentTraceEvent } from '@/lib/agentTrace';

export type AgentReplayAction =
  | 'set_tool'
  | 'set_page'
  | 'run_ai_takeoff'
  | 'approve_review'
  | 'export_outputs';

export type AgentReplayPerEventOutcome = 'applied' | 'skipped' | 'failed';

export type AgentReplayHandlers = {
  set_tool?: (args: {
    tool: string;
    context?: Record<string, unknown>;
  }) => void | Promise<void>;
  set_page?: (args: {
    documentId: string;
    page?: number;
    context?: Record<string, unknown>;
  }) => void | Promise<void>;
  run_ai_takeoff?: (args: {
    context?: Record<string, unknown>;
  }) => void | Promise<void>;
  approve_review?: (args: {
    context?: Record<string, unknown>;
  }) => void | Promise<void>;
  export_outputs?: (args: {
    context?: Record<string, unknown>;
  }) => void | Promise<void>;
};

export type AgentReplayEventOutcome = {
  id: string;
  event: string;
  outcome: AgentReplayPerEventOutcome;
  action?: AgentReplayAction;
  reason?: string;
};

export type ReplayAgentTraceEventsResult = {
  outcomes: AgentReplayEventOutcome[];
  counts: { applied: number; skipped: number; failed: number };
};

export type ReplayAgentTraceEventsOptions = {
  dryRun?: boolean;
};

const TRACE_EVENT_TO_ACTION: Record<string, AgentReplayAction> = {
  tool_selected: 'set_tool',
  sheet_selected: 'set_page',
  run_ai_takeoff_started: 'run_ai_takeoff',
  review_approve_all: 'approve_review',
  export_paintbrush_csv: 'export_outputs',
};

function readString(
  ctx: Record<string, unknown> | undefined,
  key: string
): string | undefined {
  const v = ctx?.[key];
  return typeof v === 'string' && v.length > 0 ? v : undefined;
}

function readOptionalPage(
  ctx: Record<string, unknown> | undefined
): number | undefined {
  const v = ctx?.page;
  if (typeof v !== 'number' || !Number.isFinite(v)) return undefined;
  const p = Math.floor(v);
  return p >= 1 ? p : undefined;
}

function sortByTsThenId(events: AgentTraceEvent[]): AgentTraceEvent[] {
  return [...events].sort((a, b) => {
    if (a.ts !== b.ts) return a.ts - b.ts;
    return a.id.localeCompare(b.id);
  });
}

function summarizeCounts(
  outcomes: AgentReplayEventOutcome[]
): ReplayAgentTraceEventsResult['counts'] {
  let applied = 0;
  let skipped = 0;
  let failed = 0;
  for (const o of outcomes) {
    if (o.outcome === 'applied') applied += 1;
    else if (o.outcome === 'skipped') skipped += 1;
    else failed += 1;
  }
  return { applied, skipped, failed };
}

/** Dry-run: no handlers; applied only when mapping + required context exist. */
function dryRunEvaluateEvent(e: AgentTraceEvent): AgentReplayEventOutcome {
  const action = TRACE_EVENT_TO_ACTION[e.event];
  if (!action) {
    return {
      id: e.id,
      event: e.event,
      outcome: 'skipped',
      reason: 'event type has no replay mapping',
    };
  }

  const ctx = e.context;
  switch (action) {
    case 'set_tool': {
      if (!readString(ctx, 'tool')) {
        return {
          id: e.id,
          event: e.event,
          outcome: 'skipped',
          action,
          reason: 'missing required context: tool',
        };
      }
      return { id: e.id, event: e.event, outcome: 'applied', action };
    }
    case 'set_page': {
      if (!readString(ctx, 'documentId')) {
        return {
          id: e.id,
          event: e.event,
          outcome: 'skipped',
          action,
          reason: 'missing required context: documentId',
        };
      }
      return { id: e.id, event: e.event, outcome: 'applied', action };
    }
    case 'run_ai_takeoff':
    case 'approve_review':
    case 'export_outputs':
      return { id: e.id, event: e.event, outcome: 'applied', action };
  }
}

export async function replayAgentTraceEvents(
  events: AgentTraceEvent[],
  handlers: AgentReplayHandlers,
  options?: ReplayAgentTraceEventsOptions
): Promise<ReplayAgentTraceEventsResult> {
  const dryRun = options?.dryRun === true;
  const outcomes: AgentReplayEventOutcome[] = [];
  const sorted = sortByTsThenId(events);

  if (dryRun) {
    for (const e of sorted) {
      outcomes.push(dryRunEvaluateEvent(e));
    }
    return { outcomes, counts: summarizeCounts(outcomes) };
  }

  for (const e of sorted) {
    const action = TRACE_EVENT_TO_ACTION[e.event];
    if (!action) {
      outcomes.push({
        id: e.id,
        event: e.event,
        outcome: 'skipped',
        reason: 'event type has no replay mapping',
      });
      continue;
    }

    const ctx = e.context;

    try {
      switch (action) {
        case 'set_tool': {
          const h = handlers.set_tool;
          if (!h) {
            outcomes.push({
              id: e.id,
              event: e.event,
              outcome: 'skipped',
              action,
              reason: 'handler not registered: set_tool',
            });
            continue;
          }
          const tool = readString(ctx, 'tool');
          if (!tool) {
            outcomes.push({
              id: e.id,
              event: e.event,
              outcome: 'skipped',
              action,
              reason: 'missing required context: tool',
            });
            continue;
          }
          await h({ tool, context: ctx });
          break;
        }
        case 'set_page': {
          const h = handlers.set_page;
          if (!h) {
            outcomes.push({
              id: e.id,
              event: e.event,
              outcome: 'skipped',
              action,
              reason: 'handler not registered: set_page',
            });
            continue;
          }
          const documentId = readString(ctx, 'documentId');
          if (!documentId) {
            outcomes.push({
              id: e.id,
              event: e.event,
              outcome: 'skipped',
              action,
              reason: 'missing required context: documentId',
            });
            continue;
          }
          const page = readOptionalPage(ctx);
          await h(
            page !== undefined
              ? { documentId, page, context: ctx }
              : { documentId, context: ctx }
          );
          break;
        }
        case 'run_ai_takeoff': {
          const h = handlers.run_ai_takeoff;
          if (!h) {
            outcomes.push({
              id: e.id,
              event: e.event,
              outcome: 'skipped',
              action,
              reason: 'handler not registered: run_ai_takeoff',
            });
            continue;
          }
          await h({ context: ctx });
          break;
        }
        case 'approve_review': {
          const h = handlers.approve_review;
          if (!h) {
            outcomes.push({
              id: e.id,
              event: e.event,
              outcome: 'skipped',
              action,
              reason: 'handler not registered: approve_review',
            });
            continue;
          }
          await h({ context: ctx });
          break;
        }
        case 'export_outputs': {
          const h = handlers.export_outputs;
          if (!h) {
            outcomes.push({
              id: e.id,
              event: e.event,
              outcome: 'skipped',
              action,
              reason: 'handler not registered: export_outputs',
            });
            continue;
          }
          await h({ context: ctx });
          break;
        }
      }
      outcomes.push({
        id: e.id,
        event: e.event,
        outcome: 'applied',
        action,
      });
    } catch (err) {
      const reason =
        err instanceof Error && err.message
          ? err.message
          : 'handler threw an error';
      outcomes.push({
        id: e.id,
        event: e.event,
        outcome: 'failed',
        action,
        reason,
      });
    }
  }

  return { outcomes, counts: summarizeCounts(outcomes) };
}
