'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import type { AgentEntry } from '@/features/agents/registry';
import type { AgentId, AgentModule } from '@/features/agents/types';

const loaded = new Map<AgentId, AgentModule>();

type State = { id: AgentId | null; module: AgentModule | null; failed: boolean };

/**
 * An agent's screens, loaded when the agent is first opened (each agent is its own chunk). While they load, `module` is null and the dashboard
 * draws the sidebar with only the navigation and the page as skeletons. An agent opened before in this visit is there at once.
 */
export function useAgentModule(agent: AgentEntry | null): { module: AgentModule | null; failed: boolean; retry: () => void } {
  const [state, setState] = useState<State>({ id: null, module: null, failed: false });
  const [attempt, setAttempt] = useState(0);
  // The effect follows the agent's id, not the object, so a caller that builds a new object each time cannot start it over and over.
  const latest = useRef(agent);
  latest.current = agent;
  const id = agent?.id ?? null;

  useEffect(() => {
    const current = latest.current;
    if (!current || current.id !== id) return;
    const cached = loaded.get(current.id);
    if (cached) {
      setState({ id: current.id, module: cached, failed: false });
      return;
    }
    let live = true;
    setState({ id: current.id, module: null, failed: false });
    current
      .load()
      .then((module) => {
        loaded.set(current.id, module);
        if (live) setState({ id: current.id, module, failed: false });
      })
      .catch(() => {
        if (live) setState({ id: current.id, module: null, failed: true });
      });
    return () => {
      live = false;
    };
  }, [id, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const isCurrent = id !== null && state.id === id;
  return { module: isCurrent ? state.module : null, failed: isCurrent && state.failed, retry };
}

/** For tests. */
export const forgetLoadedAgents = (): void => loaded.clear();
