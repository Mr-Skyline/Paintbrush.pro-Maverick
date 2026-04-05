/**
 * Agent / operator trace utilities for training and replay scaffolding.
 * Persists to localStorage in the browser; no-ops safely elsewhere (SSR, Node).
 */

const STORAGE_KEY = 'paintbrush.agent_trace.v1';
const MAX_EVENTS = 5000;
const DEFAULT_TOP_EVENTS = 10;

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

/** Event names that replay tooling may subscribe to; superset of training-critical signals. */
export const REPLAYABLE_TRACE_EVENTS: readonly string[] = [
  'tool_selected',
  'sheet_selected',
  'run_ai_takeoff_started',
  'review_approve_all',
  'export_paintbrush_csv',
  'download_project_zip',
  'session_start',
  'session_end',
] as const satisfies readonly string[];

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
    // Quota or privacy mode: drop persistence for this write.
  }
}

function trimToCap(events: AgentTraceEvent[]): AgentTraceEvent[] {
  if (events.length <= MAX_EVENTS) return events;
  return events.slice(events.length - MAX_EVENTS);
}

const replayableSet = new Set<string>(REPLAYABLE_TRACE_EVENTS);

const EMPTY_CATEGORY: Record<AgentTraceCategory, number> = {
  session: 0,
  tool: 0,
  sheet: 0,
  ai: 0,
  review: 0,
  export: 0,
  navigation: 0,
  system: 0,
  data: 0,
  misc: 0,
};

const EMPTY_RESULT: Record<AgentTraceResult, number> = {
  success: 0,
  failure: 0,
  cancelled: 0,
  skipped: 0,
  pending: 0,
  unknown: 0,
};

function cloneEvent(e: AgentTraceEvent): AgentTraceEvent {
  return {
    ...e,
    ...(e.context !== undefined ? { context: { ...e.context } } : {}),
  };
}

/** All stored events, oldest first (append order). */
export function listAgentTraceEvents(): AgentTraceEvent[] {
  return loadEventsInternal().map(cloneEvent);
}

/** Most recent events first. If `limit` is omitted, returns all events in reverse chronological order. */
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

export function recordAgentTrace(
  event: Omit<AgentTraceEvent, 'id' | 'ts'>
): AgentTraceEvent {
  const full: AgentTraceEvent = {
    id: newTraceId(),
    ts: Date.now(),
    ...event,
    ...(event.context !== undefined ? { context: { ...event.context } } : {}),
  };
  if (!isBrowserStorageAvailable()) return full;
  const next = trimToCap([...loadEventsInternal(), full]);
  persistEvents(next);
  return cloneEvent(full);
}

export function recordAgentTraceSessionStart(
  context?: Record<string, unknown>
): AgentTraceEvent {
  return recordAgentTrace({
    event: 'session_start',
    category: 'session',
    result: 'success',
    ...(context !== undefined ? { context: { ...context } } : {}),
  });
}

export function recordAgentTraceSessionEnd(
  context?: Record<string, unknown>
): AgentTraceEvent {
  return recordAgentTrace({
    event: 'session_end',
    category: 'session',
    result: 'success',
    ...(context !== undefined ? { context: { ...context } } : {}),
  });
}

export function downloadAgentTraceJsonl(fileName?: string): {
  ok: boolean;
  count: number;
} {
  const events = loadEventsInternal();
  if (!isBrowserStorageAvailable()) return { ok: false, count: 0 };
  if (typeof document === 'undefined') return { ok: false, count: events.length };

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

export function getAgentTraceSummary(lastN?: number): {
  total: number;
  windowCount: number;
  byCategory: Record<AgentTraceCategory, number>;
  byResult: Record<AgentTraceResult, number>;
  topEvents: Array<{ event: string; count: number }>;
} {
  const all = loadEventsInternal();
  const total = all.length;
  let window: AgentTraceEvent[];
  if (lastN === undefined) {
    window = all;
  } else {
    const n = Math.max(0, Math.floor(lastN));
    window = n === 0 ? [] : all.slice(Math.max(0, all.length - n));
  }
  const windowCount = window.length;

  const byCategory: Record<AgentTraceCategory, number> = { ...EMPTY_CATEGORY };
  const byResult: Record<AgentTraceResult, number> = { ...EMPTY_RESULT };
  const eventCounts = new Map<string, number>();

  for (const e of window) {
    const cat = e.category in byCategory ? e.category : ('misc' as AgentTraceCategory);
    byCategory[cat] = (byCategory[cat] ?? 0) + 1;
    const res = e.result in byResult ? e.result : ('unknown' as AgentTraceResult);
    byResult[res] = (byResult[res] ?? 0) + 1;
    eventCounts.set(e.event, (eventCounts.get(e.event) ?? 0) + 1);
  }

  const topEvents = [...eventCounts.entries()]
    .map(([event, count]) => ({ event, count }))
    .sort((a, b) => b.count - a.count || a.event.localeCompare(b.event))
    .slice(0, DEFAULT_TOP_EVENTS);

  return { total, windowCount, byCategory, byResult, topEvents };
}

/** Replayable events only, most recent first. */
export function getReplayableTraceEvents(limit?: number): AgentTraceEvent[] {
  const all = loadEventsInternal();
  const filtered: AgentTraceEvent[] = [];
  for (let i = all.length - 1; i >= 0; i--) {
    const e = all[i];
    if (replayableSet.has(e.event)) filtered.push(cloneEvent(e));
  }
  if (limit === undefined) return filtered;
  const n = Math.max(0, Math.floor(limit));
  return filtered.slice(0, n);
}
