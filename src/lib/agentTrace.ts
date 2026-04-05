/**
 * Agent trace: browser localStorage (`paintbrush.agent_trace.v1`), capped at 5000 events (keep newest).
 * No-ops when localStorage/window/document are unavailable (SSR, Node).
 */

const STORAGE_KEY = 'paintbrush.agent_trace.v1';
const CURRENT_SESSION_KEY = 'paintbrush.agent_trace.current_session.v1';
const MAX_EVENTS = 5000;

export type AgentTraceCategory = 'action' | 'decision' | 'outcome' | 'session';

export type AgentTraceResult = 'success' | 'error' | 'neutral';

export type AgentTraceEvent = {
  id: string;
  ts: number;
  sessionId: string;
  category: AgentTraceCategory;
  event: string;
  reason?: string;
  result?: AgentTraceResult;
  context?: Record<string, unknown>;
};

export type AgentTraceEventInput = Omit<
  AgentTraceEvent,
  'id' | 'ts' | 'sessionId'
> & {
  sessionId?: string;
};

function hasWindow(): boolean {
  return typeof globalThis !== 'undefined' && typeof (globalThis as { window?: unknown }).window !== 'undefined';
}

function hasDocument(): boolean {
  return typeof globalThis !== 'undefined' && typeof (globalThis as { document?: unknown }).document !== 'undefined';
}

function isBrowserStorageAvailable(): boolean {
  if (!hasWindow()) return false;
  try {
    const ls = (globalThis as { localStorage?: Storage | null }).localStorage;
    return ls !== undefined && ls !== null;
  } catch {
    return false;
  }
}

function newTraceId(): string {
  const c =
    typeof globalThis !== 'undefined' && 'crypto' in globalThis
      ? (globalThis as { crypto?: Crypto }).crypto
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

const LEGACY_CATEGORIES: Record<string, AgentTraceCategory> = {
  session: 'session',
  tool: 'action',
  sheet: 'action',
  ai: 'action',
  review: 'decision',
  export: 'action',
  navigation: 'action',
  system: 'outcome',
  data: 'action',
  misc: 'outcome',
};

const LEGACY_RESULTS: Record<string, AgentTraceResult> = {
  success: 'success',
  failure: 'error',
  error: 'error',
  ok: 'success',
  cancelled: 'neutral',
  skipped: 'neutral',
  pending: 'neutral',
  unknown: 'neutral',
};

function migrateCategory(c: string): AgentTraceCategory {
  if (c === 'action' || c === 'decision' || c === 'outcome' || c === 'session') return c;
  return LEGACY_CATEGORIES[c] ?? 'outcome';
}

function migrateResult(r: unknown): AgentTraceResult | undefined {
  if (r === undefined || r === null) return undefined;
  if (typeof r !== 'string') return 'neutral';
  if (r === 'success' || r === 'error' || r === 'neutral') return r;
  return LEGACY_RESULTS[r] ?? 'neutral';
}

function isPlainObject(x: unknown): x is Record<string, unknown> {
  return x !== null && typeof x === 'object' && !Array.isArray(x);
}

function isAgentTraceEvent(x: unknown): x is AgentTraceEvent {
  if (!isPlainObject(x)) return false;
  const o = x;
  return (
    typeof o.id === 'string' &&
    typeof o.ts === 'number' &&
    Number.isFinite(o.ts) &&
    typeof o.event === 'string' &&
    typeof o.category === 'string'
  );
}

function normalizeEvents(raw: unknown): AgentTraceEvent[] {
  if (!Array.isArray(raw)) return [];
  const out: AgentTraceEvent[] = [];
  for (const item of raw) {
    if (!isAgentTraceEvent(item)) continue;
    const ev: AgentTraceEvent = {
      id: item.id,
      ts: item.ts,
      sessionId: typeof item.sessionId === 'string' ? item.sessionId : '',
      event: item.event,
      category: migrateCategory(item.category as string),
    };
    const res = migrateResult(item.result);
    if (res !== undefined) ev.result = res;
    if (typeof item.reason === 'string') ev.reason = item.reason;
    if (item.context !== undefined && isPlainObject(item.context)) {
      ev.context = { ...item.context };
    }
    out.push(ev);
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
  const copy: AgentTraceEvent = {
    id: e.id,
    ts: e.ts,
    sessionId: e.sessionId,
    category: e.category,
    event: e.event,
  };
  if (e.reason !== undefined) copy.reason = e.reason;
  if (e.result !== undefined) copy.result = e.result;
  if (e.context !== undefined) copy.context = { ...e.context };
  return copy;
}

export function listAgentTraceEvents(): AgentTraceEvent[] {
  return loadEventsInternal().map(cloneEvent);
}

export function clearAgentTraceEvents(): void {
  if (!isBrowserStorageAvailable()) return;
  try {
    globalThis.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

function readCurrentSessionIdRaw(): string | null {
  if (!isBrowserStorageAvailable()) return null;
  try {
    return globalThis.localStorage.getItem(CURRENT_SESSION_KEY);
  } catch {
    return null;
  }
}

function writeCurrentSessionIdRaw(id: string | null): void {
  if (!isBrowserStorageAvailable()) return;
  try {
    if (id == null || id === '') globalThis.localStorage.removeItem(CURRENT_SESSION_KEY);
    else globalThis.localStorage.setItem(CURRENT_SESSION_KEY, id);
  } catch {
    // ignore
  }
}

export function getCurrentAgentTraceSessionId(): string | null {
  const v = readCurrentSessionIdRaw();
  return v != null && v !== '' ? v : null;
}

export function setCurrentAgentTraceSessionId(id: string | null): void {
  writeCurrentSessionIdRaw(id);
}

export function startAgentTraceSession(meta?: Record<string, unknown>): string {
  const sessionId = newTraceId();
  setCurrentAgentTraceSessionId(sessionId);
  recordAgentTraceImpl({
    sessionId,
    category: 'session',
    event: 'session_start',
    result: 'neutral',
    ...(meta !== undefined ? { context: { ...meta } } : {}),
  });
  return sessionId;
}

export function endAgentTraceSession(
  sessionId: string,
  meta?: Record<string, unknown>
): void {
  recordAgentTraceImpl({
    sessionId,
    category: 'session',
    event: 'session_end',
    result: 'neutral',
    ...(meta !== undefined ? { context: { ...meta } } : {}),
  });
  if (getCurrentAgentTraceSessionId() === sessionId) {
    setCurrentAgentTraceSessionId(null);
  }
}

function recordAgentTraceImpl(input: AgentTraceEventInput): AgentTraceEvent {
  const sid =
    input.sessionId !== undefined && input.sessionId !== ''
      ? input.sessionId
      : getCurrentAgentTraceSessionId() ?? '';
  const full: AgentTraceEvent = {
    id: newTraceId(),
    ts: Date.now(),
    sessionId: sid,
    category: input.category,
    event: input.event,
    ...(input.reason !== undefined ? { reason: input.reason } : {}),
    ...(input.result !== undefined ? { result: input.result } : {}),
    ...(input.context !== undefined ? { context: { ...input.context } } : {}),
  };
  if (!isBrowserStorageAvailable()) return cloneEvent(full);
  const next = trimToCap([...loadEventsInternal(), full]);
  persistEvents(next);
  return cloneEvent(full);
}

export function recordAgentTrace(eventWithoutIdTs: AgentTraceEventInput): AgentTraceEvent {
  return recordAgentTraceImpl(eventWithoutIdTs);
}

export function downloadAgentTraceJsonl(fileName?: string): {
  ok: boolean;
  count: number;
} {
  const events = loadEventsInternal();
  if (!isBrowserStorageAvailable()) return { ok: false, count: 0 };
  if (!hasDocument()) return { ok: false, count: events.length };

  const doc = (globalThis as { document: Document }).document;
  const lines = events.map((e) => JSON.stringify(e));
  const body = lines.join('\n') + (lines.length > 0 ? '\n' : '');
  const blob = new Blob([body], { type: 'application/x-ndjson;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = doc.createElement('a');
  a.href = url;
  a.download =
    fileName?.trim() ||
    `agent-trace-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.jsonl`;
  a.rel = 'noopener';
  doc.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return { ok: true, count: events.length };
}
