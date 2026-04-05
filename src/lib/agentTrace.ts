export type AgentTraceCategory = 'action' | 'decision' | 'outcome';
export type AgentTraceResult = 'success' | 'error' | 'neutral';

export interface AgentTraceEvent {
  id: string;
  ts: string;
  category: AgentTraceCategory;
  event: string;
  reason?: string;
  result?: AgentTraceResult;
  context?: Record<string, unknown>;
}

const TRACE_KEY = 'paintbrush.agent_trace.v1';
const TRACE_LIMIT = 5000;

function nowIso() {
  return new Date().toISOString();
}

function nextId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
}

function hasStorage() {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

function readRaw(): AgentTraceEvent[] {
  if (!hasStorage()) return [];
  try {
    const raw = window.localStorage.getItem(TRACE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as AgentTraceEvent[];
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

function writeRaw(events: AgentTraceEvent[]) {
  if (!hasStorage()) return;
  try {
    window.localStorage.setItem(TRACE_KEY, JSON.stringify(events));
  } catch {
    // Ignore storage quota or serialization errors.
  }
}

export function listAgentTraceEvents(): AgentTraceEvent[] {
  return readRaw();
}

export function clearAgentTraceEvents() {
  if (!hasStorage()) return;
  window.localStorage.removeItem(TRACE_KEY);
}

export function recordAgentTrace(
  event: Omit<AgentTraceEvent, 'id' | 'ts'>
): AgentTraceEvent {
  const row: AgentTraceEvent = {
    id: nextId(),
    ts: nowIso(),
    ...event,
  };
  const existing = readRaw();
  const next =
    existing.length >= TRACE_LIMIT
      ? [...existing.slice(existing.length - TRACE_LIMIT + 1), row]
      : [...existing, row];
  writeRaw(next);
  return row;
}

export function downloadAgentTraceJsonl(fileName?: string): {
  ok: boolean;
  count: number;
} {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return { ok: false, count: 0 };
  }
  const rows = listAgentTraceEvents();
  const safeName = fileName || `agent-trace-${Date.now()}.jsonl`;
  const payload = rows.map((x) => JSON.stringify(x)).join('\n');
  const blob = new Blob([payload], { type: 'application/x-ndjson' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = safeName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return { ok: true, count: rows.length };
}
