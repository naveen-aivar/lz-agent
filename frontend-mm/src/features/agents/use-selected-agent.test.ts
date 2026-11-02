import { describe, expect, it } from 'vitest';

import { DEFAULT_AGENT_ID } from '@/features/agents/registry';
import { resolveAgentId } from '@/features/agents/use-selected-agent';

describe('resolveAgentId', () => {
  it('takes the agent in the address first, then the one used last, then the default (connected) agent', () => {
    expect(resolveAgentId('?agent=tco', 'seven-rs')).toBe('tco');
    expect(resolveAgentId('', 'seven-rs')).toBe('seven-rs');
    expect(resolveAgentId('', null)).toBe(DEFAULT_AGENT_ID);
  });

  it('ignores a name nobody knows, in the address or in storage', () => {
    expect(resolveAgentId('?agent=backup-dr', 'architecture-design')).toBe('architecture-design');
    expect(resolveAgentId('?agent=%3Cscript%3E', 'nonsense')).toBe(DEFAULT_AGENT_ID);
  });
});
