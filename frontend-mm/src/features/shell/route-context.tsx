'use client';

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import type { AgentId, AgentRoute, Navigate } from '@/features/agents/types';

interface RouteState {
  route: AgentRoute;
  navigate: Navigate;
}

const Ctx = createContext<RouteState | null>(null);

/** The page each agent was on when it was left, so coming back to an agent in the same visit puts you where you were. */
const lastRoutes = new Map<AgentId, AgentRoute>();

/** For tests: forget every agent's last page. */
export const forgetLastRoutes = (): void => lastRoutes.clear();

/**
 * Where the open agent is. The dashboard is one page at one address, so this is state, not the address: nothing changes in the browser's address
 * bar when an agent or a page changes. Mounted once per agent (the caller keys it by the agent).
 */
export function AgentRouteProvider({ agentId, defaultPage, children }: { agentId: AgentId; defaultPage: string; children: ReactNode }) {
  const [route, setRoute] = useState<AgentRoute>(() => lastRoutes.get(agentId) ?? { page: defaultPage, params: {} });
  const navigate = useCallback<Navigate>(
    (page, params = {}) => {
      const next = { page, params };
      lastRoutes.set(agentId, next);
      setRoute(next);
    },
    [agentId],
  );
  const value = useMemo(() => ({ route, navigate }), [route, navigate]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAgentRoute(): RouteState {
  const value = useContext(Ctx);
  if (!value) throw new Error('useAgentRoute must be used inside an AgentRouteProvider');
  return value;
}
