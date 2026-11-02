import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
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

import { Dashboard } from '@/features/shell/dashboard';
import { forgetLastRoutes } from '@/features/shell/route-context';
import { alphaLoad, alphaModule, betaLoad, betaModule } from '@/features/shell/test-agents';
import { forgetLoadedAgents } from '@/features/shell/use-agent-module';

beforeEach(() => {
  window.localStorage.clear();
  forgetLoadedAgents();
  forgetLastRoutes();
  alphaLoad.mockReset().mockResolvedValue(alphaModule);
  betaLoad.mockReset().mockResolvedValue(betaModule);
});

describe('Dashboard', () => {
  it('opens the first agent: one sidebar with its navigation, the top bar breadcrumb and its first page', async () => {
    render(<Dashboard />);
    expect(await screen.findByText('Alpha page: start')).toBeInTheDocument();
    expect(screen.getAllByRole('complementary')).toHaveLength(1); // one sidebar
    const crumbs = within(screen.getByRole('navigation', { name: 'Breadcrumb' }));
    expect(crumbs.getByText('Ingram Micro Agents')).toBeInTheDocument();
    expect(crumbs.getByText('Alpha Agent')).toBeInTheDocument();
    expect(crumbs.getByText('Alpha start')).toHaveAttribute('aria-current', 'page');
    expect(document.title).toBe('Alpha start | Alpha Agent | Ingram Micro');
  });

  it('moves between the agent’s pages from the sidebar and from inside a page, without changing the address', async () => {
    const before = window.location.href;
    render(<Dashboard />);
    await screen.findByText('Alpha page: start');
    await userEvent.click(screen.getByRole('button', { name: /Configuration/ }));
    expect(await screen.findByText('Alpha page: config')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /2\. Review/ }));
    expect(await screen.findByText('Alpha page: review')).toBeInTheDocument();
    await userEvent.click(screen.getByText('go to configuration'));
    expect(await screen.findByText('Alpha page: config')).toBeInTheDocument();
    expect(window.location.href).toBe(before);
  });

  it('switches the whole dashboard to another agent: while it loads the sidebar keeps what it knows, switched off, and only the navigation is a skeleton', async () => {
    let resolveBeta!: (m: typeof betaModule) => void;
    betaLoad.mockReturnValue(new Promise((r) => (resolveBeta = r)));
    render(<Dashboard />);
    await screen.findByText('Alpha page: start');
    await userEvent.click(screen.getByRole('button', { name: /Switch agent/ }));
    await userEvent.click(within(await screen.findByRole('dialog', { name: 'Switch agent' })).getByRole('button', { name: /Beta Review/ }));

    // loading
    expect(await screen.findByRole('status', { name: 'Opening Beta Review' })).toBeInTheDocument();
    expect(screen.getByText('Beta Review', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Loading the navigation' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Switch agent Beta Review' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeDisabled();
    expect(screen.getByText('Priya Nair')).toBeInTheDocument();
    expect(screen.queryByText('Alpha page: start')).toBeNull();

    // ready
    await act(async () => resolveBeta(betaModule));
    expect(await screen.findByText('Beta portfolio')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Switch agent Beta Review' })).toBeEnabled();
    expect(screen.queryByRole('status', { name: /Opening/ })).toBeNull();
    expect(window.localStorage.getItem('mm.agent')).toBe('tco');
  });

  it('clears the messages of the agent that was open when the person switches to another', async () => {
    const dismiss = vi.spyOn(toast, 'dismiss');
    render(<Dashboard />);
    await screen.findByText('Alpha page: start');
    dismiss.mockClear();
    await userEvent.click(screen.getByRole('button', { name: /Switch agent/ }));
    await userEvent.click(within(await screen.findByRole('dialog', { name: 'Switch agent' })).getByRole('button', { name: /Beta Review/ }));
    await screen.findByText('Beta portfolio');
    expect(dismiss).toHaveBeenCalled();
    dismiss.mockRestore();
  });

  it('brings an agent back on the page it was left on', async () => {
    render(<Dashboard />);
    await screen.findByText('Alpha page: start');
    await userEvent.click(screen.getByRole('button', { name: /Configuration/ }));
    await screen.findByText('Alpha page: config');
    await userEvent.click(screen.getByRole('button', { name: /Switch agent/ }));
    await userEvent.click(within(await screen.findByRole('dialog', { name: 'Switch agent' })).getByRole('button', { name: /Beta Review/ }));
    await screen.findByText('Beta portfolio');
    await userEvent.click(screen.getByRole('button', { name: /Switch agent/ }));
    await userEvent.click(within(await screen.findByRole('dialog', { name: 'Switch agent' })).getByRole('button', { name: /Alpha Agent/ }));
    expect(await screen.findByText('Alpha page: config')).toBeInTheDocument();
  });

  it('says so and offers to try again when an agent’s screens cannot be loaded, and lets the person leave', async () => {
    betaLoad.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(betaModule);
    window.localStorage.setItem('mm.agent', 'tco');
    render(<Dashboard />);
    expect(await screen.findByText('We could not open Beta Review')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Switch agent Beta Review' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Beta portfolio')).toBeInTheDocument();
  });

  it('keeps the dashboard standing when a page fails to draw', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    alphaLoad.mockResolvedValue({
      ...alphaModule,
      Screen: ({ route }: { route: { page: string } }) => {
        if (route.page === 'config') throw new Error('boom');
        return <p>fine: {route.page}</p>;
      },
    });
    render(<Dashboard />);
    await screen.findByText('fine: start');
    await userEvent.click(screen.getByRole('button', { name: /Configuration/ }));
    expect(await screen.findByText('This page could not be shown')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /1\. Start/ })); // the sidebar still works
    await waitFor(() => expect(screen.getByText('fine: start')).toBeInTheDocument());
    spy.mockRestore();
  });
});
