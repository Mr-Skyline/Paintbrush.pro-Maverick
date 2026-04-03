export type AgentBoostScope = 'page' | 'all';

export interface AgentHostHandlers {
  runBoost?: (
    scope: AgentBoostScope
  ) => Promise<{ ok: boolean; error?: string; headline?: string }>;
  openBoostDialog?: () => void;
  goToProjects?: () => void;
  saveProject?: () => Promise<{ ok: boolean; error?: string }>;
}

let host: AgentHostHandlers = {};

export function setAgentHostHandlers(next: AgentHostHandlers) {
  host = next;
}

export function getAgentHostHandlers(): AgentHostHandlers {
  return host;
}
