import type { AgentId } from '@/features/agents/types';

/**
 * Where an agent's API is, for the dashboard: the same address as the dashboard, under /agents/<id>/. CloudFront sends /agents/<id>/api/... to that
 * agent's own live API (see infra/ and agents/<id>/manifest.json), so the browser only ever talks to one origin and no CORS is involved.
 * An agent's client puts this in front of the paths it already uses ("/api/runs" becomes "/agents/tco/api/runs").
 */
export const agentApiBase = (id: AgentId): string => `/agents/${id}`;
