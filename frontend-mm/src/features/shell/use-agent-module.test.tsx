import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AgentEntry } from '@/features/agents/registry';
import type { AgentModule } from '@/features/agents/types';
import { forgetLoadedAgents, useAgentModule } from '@/features/shell/use-agent-module';

const fake = (id: string): AgentModule => ({ id: id as AgentModule['id'], defaultPage: 'a', nav: [], Screen: () => null, titleOf: () => 'A' });
const entry = (id: string, load: () => Promise<AgentModule>) => ({ id, name: id, load }) as unknown as AgentEntry;

beforeEach(forgetLoadedAgents);

describe('useAgentModule', () => {
  it('has nothing while an agent’s screens load, then the module', async () => {
    let resolve!: (m: AgentModule) => void;
    const agent = entry('mra', () => new Promise((r) => (resolve = r)));
    const { result } = renderHook(() => useAgentModule(agent));
    expect(result.current.module).toBeNull();
    expect(result.current.failed).toBe(false);
    await act(async () => resolve(fake('mra')));
    expect(result.current.module?.id).toBe('mra');
  });

  it('does not load an agent a second time: coming back to it is at once', async () => {
    const load = vi.fn().mockResolvedValue(fake('seven-rs'));
    const sre = entry('seven-rs', load);
    const first = renderHook(() => useAgentModule(sre));
    await waitFor(() => expect(first.result.current.module).not.toBeNull());
    first.unmount();
    const second = renderHook(() => useAgentModule(sre));
    await waitFor(() => expect(second.result.current.module?.id).toBe('seven-rs'));
    expect(load).toHaveBeenCalledOnce();
  });

  it('says it failed, and tries again when asked', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(fake('tco'));
    const wafr = entry('tco', load);
    const { result } = renderHook(() => useAgentModule(wafr));
    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.module).toBeNull();
    await act(async () => result.current.retry());
    await waitFor(() => expect(result.current.module?.id).toBe('tco'));
    expect(result.current.failed).toBe(false);
  });

  it('is not started over by a caller that builds a new agent object on every render', async () => {
    const load = vi.fn().mockResolvedValue(fake('architecture-design'));
    const { result } = renderHook(() => useAgentModule(entry('architecture-design', load)));
    await waitFor(() => expect(result.current.module?.id).toBe('architecture-design'));
    expect(load).toHaveBeenCalledOnce();
  });

  it('never shows the previous agent’s module for a new agent', async () => {
    const a = entry('cva-output', () => Promise.resolve(fake('cva-output')));
    const b = entry('architecture-design', () => new Promise(() => {}));
    const { result, rerender } = renderHook(({ agent }) => useAgentModule(agent), { initialProps: { agent: a } });
    await waitFor(() => expect(result.current.module?.id).toBe('cva-output'));
    rerender({ agent: b });
    expect(result.current.module).toBeNull();
  });
});
