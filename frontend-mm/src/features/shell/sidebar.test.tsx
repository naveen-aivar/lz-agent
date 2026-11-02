import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/features/agents/registry', async () => {
  const { fakeAgents } = await import('@/features/shell/test-agents');
  const agents = fakeAgents();
  return { AGENTS: agents, agentById: (id: string) => agents.find((a) => a.id === id), DEFAULT_AGENT_ID: 'mra' };
});
vi.mock('@/shared/auth/config', () => ({ authEnabled: true }));
vi.mock('@/shared/auth/auth-store', () => ({
  useAuth: () => ({ status: 'signed-in', email: 'priya.nair@example.com', name: 'Priya Nair' }),
  displayName: ({ name }: { name: string }) => name,
  signOutNow: vi.fn(),
}));

import { AGENTS } from '@/features/agents/registry';
import { Sidebar } from '@/features/shell/sidebar';
import { alphaModule } from '@/features/shell/test-agents';

const alpha = AGENTS[0];
const route = { page: 'start', params: {} };

beforeEach(() => window.localStorage.clear());

describe('Sidebar, with the agent ready', () => {
  it('shows the agent’s name and subtitle, its navigation in sections, and the one that is open as the current page', () => {
    render(<Sidebar agent={alpha} module={alphaModule} route={route} navigate={vi.fn()} onSelectAgent={vi.fn()} />);
    expect(screen.getByText('Alpha Agent', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Demonstration pilot')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Agent run' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Setup' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /1\. Start/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('button', { name: /Configuration/ })).not.toHaveAttribute('aria-current');
  });

  it('opens a page when its entry is pressed, and shows a badge the agent gives it', async () => {
    const navigate = vi.fn();
    render(<Sidebar agent={alpha} module={alphaModule} route={route} navigate={navigate} onSelectAgent={vi.fn()} />);
    expect(within(screen.getByRole('button', { name: /2\. Review/ })).getByText('17')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Configuration/ }));
    expect(navigate).toHaveBeenCalledWith('config');
  });

  it('lights a different entry when the agent says which one a page belongs to', () => {
    const lit = { ...alphaModule, activeNav: () => 'review' };
    render(<Sidebar agent={alpha} module={lit} route={{ page: 'run', params: {} }} navigate={vi.fn()} onSelectAgent={vi.fn()} />);
    expect(screen.getByRole('button', { name: /2\. Review/ })).toHaveAttribute('aria-current', 'page');
  });

  it('has Switch agent just above the person’s card, both switched on', () => {
    render(<Sidebar agent={alpha} module={alphaModule} route={route} navigate={vi.fn()} onSelectAgent={vi.fn()} />);
    const switcher = screen.getByRole('button', { name: 'Switch agent Alpha Agent' });
    const signOut = screen.getByRole('button', { name: 'Sign out' });
    expect(switcher).toBeEnabled();
    expect(signOut).toBeEnabled();
    expect(screen.getByText('Priya Nair')).toBeInTheDocument();
    expect(switcher.compareDocumentPosition(signOut) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // the switch comes first, the person after it
  });

  it('shows only icons when collapsed, and remembers that for the next visit', async () => {
    render(<Sidebar agent={alpha} module={alphaModule} route={route} navigate={vi.fn()} onSelectAgent={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }));
    expect(screen.queryByText('Demonstration pilot')).toBeNull();
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false');
    expect(window.localStorage.getItem('mm.sidebar.collapsed')).toBe('true');
    expect(screen.getByRole('button', { name: /1\. Start/ })).toBeInTheDocument(); // still reachable by name
  });
});

describe('Sidebar, while the agent’s screens are still loading', () => {
  it('keeps what is known real (the agent’s name, the switch, the person) and switches the switch and the person off; only the navigation is a skeleton', () => {
    render(<Sidebar agent={alpha} module={null} route={null} navigate={vi.fn()} onSelectAgent={vi.fn()} />);
    expect(screen.getByText('Alpha Agent', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Priya Nair')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Switch agent Alpha Agent' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeDisabled();
    expect(screen.getByRole('status', { name: 'Loading the navigation' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Start/ })).toBeNull();
  });

  it('lets the person leave an agent that failed to open: Switch agent is on', () => {
    render(<Sidebar agent={alpha} module={null} route={null} navigate={vi.fn()} onSelectAgent={vi.fn()} failed />);
    expect(screen.getByRole('button', { name: 'Switch agent Alpha Agent' })).toBeEnabled();
  });
});
