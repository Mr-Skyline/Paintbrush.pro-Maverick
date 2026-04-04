import type { CvTakeoffResult } from '@/lib/cvTypes';

export interface SidekickChatReply {
  reply: string;
}

export interface ScheduleEventInput {
  projectId: string;
  title: string;
  startsAtIso: string;
  notes?: string;
}

async function parseJson<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message =
      (data as { error?: string })?.error || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data as T;
}

export async function runTakeoffUpload(
  file: File,
  projectId: string
): Promise<CvTakeoffResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('projectId', projectId);
  const res = await fetch('/api/takeoff/process-upload', {
    method: 'POST',
    body: form,
  });
  return parseJson<CvTakeoffResult>(res);
}

export async function sidekickChat(
  projectId: string,
  message: string
): Promise<SidekickChatReply> {
  const res = await fetch('/api/sidekick/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ projectId, message }),
  });
  return parseJson<SidekickChatReply>(res);
}

export async function createScheduleEvent(
  payload: ScheduleEventInput
): Promise<{ ok: boolean }> {
  const res = await fetch('/api/schedule/upsert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return parseJson<{ ok: boolean }>(res);
}
