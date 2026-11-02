'use client';

import { useCallback, useEffect, useState } from 'react';

import { agentById, DEFAULT_AGENT_ID, type AgentEntry, type AgentId } from '@/features/agents/registry';

const STORAGE_KEY = 'mm.agent';

/** Which agent is open: the address (?agent=tco) wins, then the one used last on this device, then the first. A name nobody knows is ignored. */
export function resolveAgentId(search: string, stored: string | null): AgentId {
  const fromAddress = agentById(new URLSearchParams(search).get('agent'));
  return (fromAddress ?? agentById(stored))?.id ?? DEFAULT_AGENT_ID;
}

function remember(id: AgentId) {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* private window or blocked storage: the choice just is not remembered */
  }
}

function recall(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/**
 * The open agent and a way to switch it. The address does not change when the agent does (the dashboard is one page at one address); the choice is
 * remembered for the next visit on this device. A link that names an agent (?agent=tco) still opens that one. It is read after the page has mounted,
 * because a static page cannot know the address.
 */
export function useSelectedAgent(): { agent: AgentEntry | null; select: (id: AgentId) => void } {
  const [id, setId] = useState<AgentId | null>(null);

  useEffect(() => {
    setId(resolveAgentId(window.location.search, recall()));
  }, []);

  const select = useCallback((next: AgentId) => {
    remember(next);
    setId(next);
  }, []);

  return { agent: agentById(id) ?? null, select };
}
