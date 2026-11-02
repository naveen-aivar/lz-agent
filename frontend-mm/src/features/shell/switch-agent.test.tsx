import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/features/agents/registry', async () => {
  const { fakeAgents } = await import('@/features/shell/test-agents');
  const agents = fakeAgents();
  return { AGENTS: agents, agentById: (id: string) => agents.find((a) => a.id === id), DEFAULT_AGENT_ID: 'mra' };
});

import { AGENTS } from '@/features/agents/registry';
import { SwitchAgent } from '@/features/shell/switch-agent';

const open = async (props: Partial<Parameters<typeof SwitchAgent>[0]> = {}) => {
  const onSelect = vi.fn();
  render(<SwitchAgent active={AGENTS[0]} onSelect={onSelect} {...props} />);
  await userEvent.click(screen.getByRole('button', { name: /Switch agent/ }));
  return { onSelect, list: within(await screen.findByRole('dialog', { name: 'Switch agent' })) };
};

describe('SwitchAgent', () => {
  it('says which agent is open, and lists every connected agent when opened with the open one marked', async () => {
    const { list } = await open();
    expect(screen.getByRole('button', { name: 'Switch agent Alpha Agent' })).toBeInTheDocument();
    expect(list.getAllByRole('listitem')).toHaveLength(3); // two connected agents, one upcoming
    expect(list.getByRole('button', { name: /Alpha Agent/ })).toHaveAttribute('aria-current', 'true');
  });

  it('puts an agent that is not connected yet under "Upcoming", disabled and not selectable', async () => {
    const { onSelect, list } = await open();
    const upcomingButton = list.getByRole('button', { name: /Gamma Agent/ });
    expect(list.getByText('Upcoming')).toBeInTheDocument();
    expect(upcomingButton).toBeDisabled();
    expect(list.getByText('Coming soon')).toBeInTheDocument();
    await userEvent.click(upcomingButton);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('switches to the chosen agent and closes; choosing the open one does nothing', async () => {
    const { onSelect, list } = await open();
    await userEvent.click(list.getByRole('button', { name: /Alpha Agent/ }));
    expect(onSelect).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: /Switch agent/ }));
    await userEvent.click(within(await screen.findByRole('dialog', { name: 'Switch agent' })).getByRole('button', { name: /Beta Review/ }));
    expect(onSelect).toHaveBeenCalledExactlyOnceWith('tco');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('does not offer a link out to an agent’s own site', async () => {
    const { list } = await open();
    expect(list.queryByRole('link')).toBeNull();
  });

  it('cannot be opened while switched off, and is just the icon when collapsed', async () => {
    const { rerender } = render(<SwitchAgent active={AGENTS[0]} onSelect={vi.fn()} disabled />);
    const button = screen.getByRole('button', { name: /Switch agent/ });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(screen.queryByRole('dialog')).toBeNull();
    rerender(<SwitchAgent active={AGENTS[0]} onSelect={vi.fn()} collapsed />);
    expect(screen.queryByText('Switch agent')).toBeNull(); // no visible words, the name is in the label
    expect(screen.getByRole('button', { name: 'Switch agent Alpha Agent' })).toBeEnabled();
  });
});
