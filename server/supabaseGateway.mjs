import { createClient } from '@supabase/supabase-js';

let cachedClient = null;

function getClient() {
  if (cachedClient) return cachedClient;
  const url = process.env.SUPABASE_URL?.trim();
  const key =
    process.env.SUPABASE_SERVICE_ROLE_KEY?.trim() ||
    process.env.SUPABASE_ANON_KEY?.trim();
  if (!url || !key) return null;
  cachedClient = createClient(url, key, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  return cachedClient;
}

export async function saveTakeoffResult(result) {
  const supabase = getClient();
  if (!supabase) return { ok: false, skipped: true };
  const payload = {
    project_id: result.projectId,
    source_name: result.sourceName,
    confidence: result.confidence,
    scale_label: result.scaleLabel,
    walls_count: result.walls?.length ?? 0,
    rooms_count: result.rooms?.length ?? 0,
    doors_count: result.counts?.doors ?? 0,
    windows_count: result.counts?.windows ?? 0,
    fixtures_count: result.counts?.fixtures ?? 0,
    walls_lf: result.quantities?.wallsLf ?? 0,
    rooms_sf: result.quantities?.roomsSf ?? 0,
    payload_json: result,
    audit_id: result.auditId ?? null,
    created_at: new Date().toISOString(),
  };
  const { error } = await supabase.from('takeoff_runs').insert(payload);
  return { ok: !error, error: error?.message };
}

export async function saveSidekickChat(projectId, userText, replyText) {
  const supabase = getClient();
  if (!supabase) return { ok: false, skipped: true };
  const { error } = await supabase.from('chat_logs').insert({
    project_id: projectId,
    user_text: userText,
    assistant_text: replyText,
    created_at: new Date().toISOString(),
  });
  return { ok: !error, error: error?.message };
}

export async function upsertScheduleEvent(event) {
  const supabase = getClient();
  if (!supabase) return { ok: false, skipped: true };
  const payload = {
    project_id: event.projectId,
    title: event.title,
    starts_at: event.startsAtIso,
    notes: event.notes ?? null,
    updated_at: new Date().toISOString(),
  };
  const { error } = await supabase.from('schedules').insert(payload);
  return { ok: !error, error: error?.message };
}
