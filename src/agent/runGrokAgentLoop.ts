import { GROK_AGENT_SYSTEM } from '@/agent/agentSystemPrompt';
import { buildAgentSnapshot } from '@/agent/buildAgentSnapshot';
import { executeAgentTool } from '@/agent/executeAgentTool';

function normalizeAssistantMessage(msg: Record<string, unknown>) {
  const tcs = msg.tool_calls as
    | Array<{
        id: string;
        type?: string;
        function: { name: string; arguments: unknown };
      }>
    | undefined;
  if (!tcs?.length) return msg;
  return {
    ...msg,
    tool_calls: tcs.map((tc) => ({
      id: tc.id,
      type: tc.type ?? 'function',
      function: {
        name: tc.function.name,
        arguments:
          typeof tc.function.arguments === 'string'
            ? tc.function.arguments
            : JSON.stringify(tc.function.arguments ?? {}),
      },
    })),
  };
}

/**
 * Multi-turn Grok agent: model may call tools; we execute in-browser and send results back.
 */
export async function runGrokAgentLoop(userRequest: string): Promise<{
  reply: string;
  error?: string;
}> {
  const messages: Record<string, unknown>[] = [
    { role: 'user', content: JSON.stringify({ userRequest }) },
  ];
  const maxSteps = 14;

  for (let step = 0; step < maxSteps; step++) {
    const snapshot = buildAgentSnapshot();
    const system = `${GROK_AGENT_SYSTEM}\n\n## Current app state\n\`\`\`json\n${JSON.stringify(snapshot)}\n\`\`\``;

    let res: Response;
    try {
      res = await fetch('/api/agent/step', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ system, messages }),
      });
    } catch (e) {
      return {
        reply: `Cannot reach /api/agent/step. Run "npm run dev" so the API on port 3000 is up (Vite proxies /api). ${String(e)}`,
        error: String(e),
      };
    }

    let data: {
      error?: string;
      message?: Record<string, unknown>;
      keyMissing?: boolean;
    };
    try {
      data = (await res.json()) as typeof data;
    } catch {
      return {
        reply: `API returned non-JSON (HTTP ${res.status}). Is the dev server running?`,
        error: 'bad_json',
      };
    }

    if (data.keyMissing) {
      return {
        reply:
          'Grok API key missing. Add GROK_API_KEY or XAI_API_KEY to your .env and restart the server.',
      };
    }

    if (!res.ok || data.error) {
      return {
        reply: data.error || `HTTP ${res.status}`,
        error: data.error,
      };
    }

    const raw = data.message;
    if (!raw) {
      return { reply: 'Empty response from Grok.', error: 'empty' };
    }

    const msg = normalizeAssistantMessage(raw);
    messages.push(msg);

    const toolCalls = msg.tool_calls as
      | Array<{
          id: string;
          function: { name: string; arguments: unknown };
        }>
      | undefined;

    if (toolCalls?.length) {
      for (const tc of toolCalls) {
        const result = await executeAgentTool(
          tc.function.name,
          tc.function.arguments
        );
        messages.push({
          role: 'tool',
          tool_call_id: tc.id,
          content: result.slice(0, 8000),
        });
      }
      continue;
    }

    const text =
      typeof msg.content === 'string' ? msg.content.trim() : '';
    if (text) {
      return { reply: text };
    }

    return { reply: 'Done.' };
  }

  return {
    reply:
      'Stopped after many tool steps. Ask for one thing at a time or check the console.',
  };
}
