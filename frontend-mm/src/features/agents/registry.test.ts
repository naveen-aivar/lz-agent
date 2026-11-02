import { describe, expect, it } from 'vitest';

import { AGENTS, agentById, DEFAULT_AGENT_ID } from '@/features/agents/registry';

describe('the agent registry', () => {
  it('lists the Migration and Modernization agents, once each, in the order a migration meets them', () => {
    expect(AGENTS.map((a) => a.id)).toEqual(['cva-output', 'seven-rs', 'mra', 'architecture-design', 'tco', 'orchestrator', 'landing-zone', 'migration-launch']);
    expect(new Set(AGENTS.map((a) => a.id)).size).toBe(AGENTS.length);
  });

  it('loads each agent’s module on demand, and each module is for the agent that asked', { timeout: 30_000 }, async () => {
    for (const agent of AGENTS) {
      const agentModule = await agent.load();
      expect(agentModule.id).toBe(agent.id);
      expect(agentModule.nav.flatMap((section) => section.items).map((item) => item.id)).toContain(agentModule.defaultPage);
    }
  });

  it('knows an agent by its id and nothing else', () => {
    expect(agentById('tco')?.name).toBe('TCO Agent');
    expect(agentById('backupdr')).toBeUndefined();
    expect(agentById(null)).toBeUndefined();
  });

  it('defaults to the first connected agent, not an agent that only says it is not connected yet', () => {
    expect(DEFAULT_AGENT_ID).toBe('cva-output');
    expect(agentById(DEFAULT_AGENT_ID)?.connected).toBe(true);
  });

  it('marks which agents are connected, matching whether they load real screens or the not-connected stand-in', () => {
    expect(AGENTS.filter((a) => a.connected).map((a) => a.id)).toEqual(['cva-output', 'mra', 'architecture-design', 'tco', 'orchestrator']);
  });
});
