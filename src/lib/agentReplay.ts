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

export type ReplayAgentTraceEventsResult = {
  outcomes: Array<{
    id: string;
    event: string;
    outcome: AgentReplayPerEventOutcome;
  }>;
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

export async function replayAgentTraceEvents(
  events: AgentTraceEvent[],
  handlers: AgentReplayHandlers
): Promise<ReplayAgentTraceEventsResult> {
  const outcomes: ReplayAgentTraceEventsResult['outcomes'] = [];
  const sorted = sortByTsThenId(events);

  for (const e of sorted) {
    const action = TRACE_EVENT_TO_ACTION[e.event];
    if (!action) {
      outcomes.push({ id: e.id, event: e.event, outcome: 'skipped' });
      continue;
    }

    const ctx = e.context;

    try {
      let applied = false;
      switch (action) {
        case 'set_tool': {
          const h = handlers.set_tool;
          if (!h) break;
          const tool = readString(ctx, 'tool');
          if (tool) {
            await h({ tool, context: ctx });
            applied = true;
          }
          break;
        }
        case 'set_page': {
          const h = handlers.set_page;
          if (!h) break;
          const documentId = readString(ctx, 'documentId');
          if (documentId) {
            const page = readOptionalPage(ctx);
            await h(
              page !== undefined
                ? { documentId, page, context: ctx }
                : { documentId, context: ctx }
            );
            applied = true;
          }
          break;
        }
        case 'run_ai_takeoff': {
          const h = handlers.run_ai_takeoff;
          if (!h) break;
          await h({ context: ctx });
          applied = true;
          break;
        }
        case 'approve_review': {
          const h = handlers.approve_review;
          if (!h) break;
          await h({ context: ctx });
          applied = true;
          break;
        }
        case 'export_outputs': {
          const h = handlers.export_outputs;
          if (!h) break;
          await h({ context: ctx });
          applied = true;
          break;
        }
      }
      outcomes.push({
        id: e.id,
        event: e.event,
        outcome: applied ? 'applied' : 'skipped',
      });
    } catch {
      outcomes.push({ id: e.id, event: e.event, outcome: 'failed' });
    }
  }

  return { outcomes };
}
