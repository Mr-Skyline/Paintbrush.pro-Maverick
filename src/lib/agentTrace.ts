/**
 * Agent trace: browser localStorage (`paintbrush.agent_trace.v1`), newest-first cap at 5000.
 * Read/write no-ops when localStorage is unavailable (SSR, Node).
 */

const STORAGE_KEY = 'paintbrush.agent_trace.v1';
const MAX_EVENTS = 5000;

export type AgentTraceCategory =
  | 'session'
  | 'tool'
  | 'sheet'
  | 'ai'
  | 'review'
  | 'export'
  | 'navigation'
  | 'system'
  | 'data'
  | 'misc';

export type AgentTraceResult =
  | 'success'
  | 'failure'
  | 'cancelled'
  | 'skipped'
  | 'pending'
  | 'unknown';

export type AgentTraceEvent = {
  id: string;
  ts: number;
  event: string;
  category: AgentTraceCategory;
  result: AgentTraceResult;
  context?: Record<string, unknown>;
};

/** UI axis: operational action vs branching decision vs session/meta outcome. */
export type AgentTraceAxis = 'action' | 'decision' | 'outcome';

const AXIS_ACTION: ReadonlySet<AgentTraceCategory> = new Set([
  'tool',
  'sheet',
  'navigation',
  'export',
  'data',
]);
const AXIS_DECISION: ReadonlySet<AgentTraceCategory> = new Set(['ai', 'review']);
const AXIS_OUTCOME: ReadonlySet<AgentTraceCategory> = new Set([
  'session',
  'system',
  'misc',
]);

export function categoryToTraceAxis(category: AgentTraceCategory): AgentTraceAxis {
  if (AXIS_DECISION.has(category)) return 'decision';
  if (AXIS_OUTCOME.has(category)) return 'outcome';
  if (AXIS_ACTION.has(category)) return 'action';
  return 'outcome';
}

export function countAgentTraceByAxis(events: AgentTraceEvent[]): Record<AgentTraceAxis, number> {
  const counts: Record<AgentTraceAxis, number> = {
    action: 0,
    decision: 0,
    outcome: 0,
  };
  for (const e of events) {
    counts[categoryToTraceAxis(e.category)] += 1;
  }
  return counts;
}

export function getAgentTraceViewerSnapshot(lastRecent = 20): {
  total: number;
  byAxis: Record<AgentTraceAxis, number>;
  recent: AgentTraceEvent[];
} {
  const all = loadEventsInternal();
  const total = all.length;
  const byAxis = countAgentTraceByAxis(all);
  const n = Math.max(0, Math.floor(lastRecent));
  const recent = listRecentAgentTraceEvents(n);
  return { total, byAxis, recent };
}

/** Handlers for deterministic replay of high-confidence trace steps. */
export type AgentTraceReplayHandlers = {
  onToolSelected?: (args: { tool: string }) => void | Promise<void>;
  onSheetSelected?: (args: {
    documentId: string;
    page?: number;
  }) => void | Promise<void>;
  onRunAiTakeoffStarted?: (
    context: Record<string, unknown> | undefined
  ) => void | Promise<void>;
  onReviewApproveAll?: (
    context: Record<string, unknown> | undefined
  ) => void | Promise<void>;
  onExportPaintbrushCsv?: (
    context: Record<string, unknown> | undefined
  ) => void | Promise<void>;
};

export type ReplayAgentTraceSequenceResult = {
  examined: number;
  invoked: number;
  skipped: number;
};

function isBrowserStorageAvailable(): boolean {
  return (
    typeof globalThis !== 'undefined' &&
    typeof (globalThis as unknown as { localStorage?: Storage }).localStorage !==
      'undefined' &&
    (globalThis as unknown as { localStorage: Storage }).localStorage !== null
  );
}

function newTraceId(): string {
  const c =
    typeof globalThis !== 'undefined' && 'crypto' in globalThis
      ? (globalThis as unknown as { crypto?: Crypto }).crypto
      : undefined;
  if (c?.randomUUID) return c.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function readRawEvents(): unknown {
  if (!isBrowserStorageAvailable()) return [];
  try {
    const raw = globalThis.localStorage.getItem(STORAGE_KEY);
    if (raw == null || raw === '') return [];
    return JSON.parse(raw) as unknown;
  } catch {
    return [];
  }
}

function isAgentTraceEvent(x: unknown): x is AgentTraceEvent {
  if (x === null || typeof x !== 'object') return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === 'string' &&
    typeof o.ts === 'number' &&
    Number.isFinite(o.ts) &&
    typeof o.event === 'string' &&
    typeof o.category === 'string' &&
    typeof o.result === 'string'
  );
}

function normalizeEvents(raw: unknown): AgentTraceEvent[] {
  if (!Array.isArray(raw)) return [];
  const out: AgentTraceEvent[] = [];
  for (const item of raw) {
    if (isAgentTraceEvent(item)) {
      const ev: AgentTraceEvent = {
        id: item.id,
        ts: item.ts,
        event: item.event,
        category: item.category as AgentTraceCategory,
        result: item.result as AgentTraceResult,
      };
      if (item.context !== undefined) ev.context = item.context;
      out.push(ev);
    }
  }
  return out;
}

function loadEventsInternal(): AgentTraceEvent[] {
  return normalizeEvents(readRawEvents());
}

function persistEvents(events: AgentTraceEvent[]): void {
  if (!isBrowserStorageAvailable()) return;
  try {
    globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify(events));
  } catch {
    // quota / privacy mode
  }
}

function trimToCap(events: AgentTraceEvent[]): AgentTraceEvent[] {
  if (events.length <= MAX_EVENTS) return events;
  return events.slice(events.length - MAX_EVENTS);
}

function cloneEvent(e: AgentTraceEvent): AgentTraceEvent {
  return {
    ...e,
    ...(e.context !== undefined ? { context: { ...e.context } } : {}),
  };
}

function summaryWindow(
  all: AgentTraceEvent[],
  lastN?: number
): AgentTraceEvent[] {
  if (lastN === undefined) return all;
  const n = Math.max(0, Math.floor(lastN));
  if (n === 0) return [];
  return all.slice(Math.max(0, all.length - n));
}

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

function readScope(
  ctx: Record<string, unknown> | undefined
): 'page' | 'all' | undefined {
  const v = ctx?.scope;
  return v === 'all' || v === 'page' ? v : undefined;
}

/** Deterministic replay steps derived from trace event names. */
export type ReplayCommand =
  | { type: 'tool_selected'; sourceEventId: string; ts: number; tool: string }
  | {
      type: 'sheet_selected';
      sourceEventId: string;
      ts: number;
      documentId: string;
      page?: number;
    }
  | {
      type: 'open_ai_takeoff_dialog';
      sourceEventId: string;
      ts: number;
      scope?: 'page' | 'all';
    }
  | { type: 'review_approve_all'; sourceEventId: string; ts: number }
  | { type: 'export_paintbrush_csv'; sourceEventId: string; ts: number }
  | { type: 'export_project_zip'; sourceEventId: string; ts: number };

const REPLAY_EVENT_NAMES = new Set<string>([
  'tool_selected',
  'sheet_selected',
  'open_ai_takeoff_dialog',
  'review_approve_all',
  'export_paintbrush_csv',
  'export_project_zip',
]);

export function listAgentTraceEvents(): AgentTraceEvent[] {
  return loadEventsInternal().map(cloneEvent);
}

export function listRecentAgentTraceEvents(limit?: number): AgentTraceEvent[] {
  const all = loadEventsInternal();
  const reversed = [...all].reverse().map(cloneEvent);
  if (limit === undefined) return reversed;
  const n = Math.max(0, Math.floor(limit));
  return reversed.slice(0, n);
}

export function clearAgentTraceEvents(): void {
  if (!isBrowserStorageAvailable()) return;
  try {
    globalThis.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

function recordAgentTraceImpl(
  event: Omit<AgentTraceEvent, 'id' | 'ts'>
): AgentTraceEvent {
  const full: AgentTraceEvent = {
    id: newTraceId(),
    ts: Date.now(),
    ...event,
    ...(event.context !== undefined ? { context: { ...event.context } } : {}),
  };
  if (!isBrowserStorageAvailable()) return cloneEvent(full);
  const next = trimToCap([...loadEventsInternal(), full]);
  persistEvents(next);
  return cloneEvent(full);
}

function legacyResultToTrace(r: string): AgentTraceResult {
  if (r === 'ok') return 'success';
  if (r === 'error') return 'failure';
  return 'unknown';
}

export function recordAgentTrace(
  event: Omit<AgentTraceEvent, 'id' | 'ts'>
): AgentTraceEvent;
export function recordAgentTrace(
  category: string,
  eventName: string,
  payload: { result: string; context?: Record<string, unknown> }
): AgentTraceEvent;
export function recordAgentTrace(
  eventOrCategory: Omit<AgentTraceEvent, 'id' | 'ts'> | string,
  eventName?: string,
  payload?: { result: string; context?: Record<string, unknown> }
): AgentTraceEvent {
  if (
    typeof eventOrCategory === 'string' &&
    eventName !== undefined &&
    payload !== undefined
  ) {
    return recordAgentTraceImpl({
      event: eventName,
      category: eventOrCategory as AgentTraceCategory,
      result: legacyResultToTrace(payload.result),
      ...(payload.context !== undefined
        ? { context: { ...payload.context } }
        : {}),
    });
  }
  return recordAgentTraceImpl(
    eventOrCategory as Omit<AgentTraceEvent, 'id' | 'ts'>
  );
}

export function getAgentTraceSummary(lastN?: number): {
  total: number;
  byCategory: Record<string, number>;
  byEvent: Record<string, number>;
  recent: AgentTraceEvent[];
} {
  const all = loadEventsInternal();
  const total = all.length;
  const window = summaryWindow(all, lastN);
  const byCategory: Record<string, number> = {};
  const byEvent: Record<string, number> = {};
  for (const e of window) {
    byCategory[e.category] = (byCategory[e.category] ?? 0) + 1;
    byEvent[e.event] = (byEvent[e.event] ?? 0) + 1;
  }
  const recent = [...window].reverse().map(cloneEvent);
  return { total, byCategory, byEvent, recent };
}

export function buildReplayCommandsFromTrace(
  events: AgentTraceEvent[]
): ReplayCommand[] {
  const out: ReplayCommand[] = [];
  for (const e of events) {
    const ctx = e.context;
    switch (e.event) {
      case 'tool_selected': {
        const tool = readString(ctx, 'tool');
        if (tool)
          out.push({
            type: 'tool_selected',
            sourceEventId: e.id,
            ts: e.ts,
            tool,
          });
        break;
      }
      case 'sheet_selected': {
        const documentId = readString(ctx, 'documentId');
        if (documentId)
          out.push({
            type: 'sheet_selected',
            sourceEventId: e.id,
            ts: e.ts,
            documentId,
            page: readOptionalPage(ctx),
          });
        break;
      }
      case 'open_ai_takeoff_dialog': {
        const cmd: ReplayCommand = {
          type: 'open_ai_takeoff_dialog',
          sourceEventId: e.id,
          ts: e.ts,
        };
        const scope = readScope(ctx);
        if (scope !== undefined) cmd.scope = scope;
        out.push(cmd);
        break;
      }
      case 'review_approve_all':
        out.push({
          type: 'review_approve_all',
          sourceEventId: e.id,
          ts: e.ts,
        });
        break;
      case 'export_paintbrush_csv':
        out.push({
          type: 'export_paintbrush_csv',
          sourceEventId: e.id,
          ts: e.ts,
        });
        break;
      case 'export_project_zip':
        out.push({
          type: 'export_project_zip',
          sourceEventId: e.id,
          ts: e.ts,
        });
        break;
      default:
        break;
    }
  }
  return out;
}

/** Stored events whose `event` is replayable, newest first. */
export function getReplayableTraceEvents(limit?: number): AgentTraceEvent[] {
  const all = loadEventsInternal();
  const filtered: AgentTraceEvent[] = [];
  for (let i = all.length - 1; i >= 0; i--) {
    const e = all[i];
    if (REPLAY_EVENT_NAMES.has(e.event)) filtered.push(cloneEvent(e));
  }
  if (limit === undefined) return filtered;
  const n = Math.max(0, Math.floor(limit));
  return filtered.slice(0, n);
}

export function downloadAgentTraceJsonl(fileName?: string): {
  ok: boolean;
  count: number;
} {
  const events = loadEventsInternal();
  if (!isBrowserStorageAvailable()) return { ok: false, count: 0 };
  if (typeof document === 'undefined')
    return { ok: false, count: events.length };

  const lines = events.map((e) => JSON.stringify(e));
  const body = lines.join('\n') + (lines.length > 0 ? '\n' : '');
  const blob = new Blob([body], { type: 'application/x-ndjson;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download =
    fileName?.trim() ||
    `agent-trace-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.jsonl`;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return { ok: true, count: events.length };
}

/**
 * Replay a sequence of stored events in order. Unknown event names are skipped.
 * Only invokes a handler when the event shape is sufficient for that step.
 */
export async function replayAgentTraceSequence(
  events: AgentTraceEvent[],
  handlers: AgentTraceReplayHandlers
): Promise<ReplayAgentTraceSequenceResult> {
  let examined = 0;
  let invoked = 0;
  let skipped = 0;

  for (const e of events) {
    examined += 1;
    const ctx = e.context;
    let did = false;

    switch (e.event) {
      case 'tool_selected': {
        const tool = readString(ctx, 'tool');
        if (tool && handlers.onToolSelected) {
          await handlers.onToolSelected({ tool });
          did = true;
        }
        break;
      }
      case 'sheet_selected': {
        const documentId = readString(ctx, 'documentId');
        if (documentId && handlers.onSheetSelected) {
          const page = readOptionalPage(ctx);
          await handlers.onSheetSelected(
            page !== undefined ? { documentId, page } : { documentId }
          );
          did = true;
        }
        break;
      }
      case 'run_ai_takeoff_started': {
        if (handlers.onRunAiTakeoffStarted) {
          await handlers.onRunAiTakeoffStarted(ctx);
          did = true;
        }
        break;
      }
      case 'review_approve_all': {
        if (handlers.onReviewApproveAll) {
          await handlers.onReviewApproveAll(ctx);
          did = true;
        }
        break;
      }
      case 'export_paintbrush_csv': {
        if (handlers.onExportPaintbrushCsv) {
          await handlers.onExportPaintbrushCsv(ctx);
          did = true;
        }
        break;
      }
      default:
        skipped += 1;
        continue;
    }

    if (did) invoked += 1;
    else skipped += 1;
  }

  return { examined, invoked, skipped };
}
