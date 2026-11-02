import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { AgentRouteProvider, forgetLastRoutes, useAgentRoute } from '@/features/shell/route-context';

function Probe() {
  const { route, navigate } = useAgentRoute();
  return (
    <div>
      <p data-testid="where">{`${route.page}|${JSON.stringify(route.params)}`}</p>
      <button onClick={() => navigate('run', { id: 'R-1' })}>open run</button>
    </div>
  );
}

beforeEach(forgetLastRoutes);

describe('AgentRouteProvider', () => {
  it('starts on the agent’s default page and moves between pages with their parameters, without touching the address', () => {
    const before = window.location.href;
    render(
      <AgentRouteProvider agentId="mra" defaultPage="start">
        <Probe />
      </AgentRouteProvider>,
    );
    expect(screen.getByTestId('where')).toHaveTextContent('start|{}');
    act(() => screen.getByText('open run').click());
    expect(screen.getByTestId('where')).toHaveTextContent('run|{"id":"R-1"}');
    expect(window.location.href).toBe(before);
  });

  it('puts an agent back on the page it was left on, and keeps each agent’s page apart', () => {
    const { unmount } = render(
      <AgentRouteProvider agentId="mra" defaultPage="start">
        <Probe />
      </AgentRouteProvider>,
    );
    act(() => screen.getByText('open run').click());
    unmount();
    render(
      <AgentRouteProvider agentId="mra" defaultPage="start">
        <Probe />
      </AgentRouteProvider>,
    );
    expect(screen.getByTestId('where')).toHaveTextContent('run|{"id":"R-1"}');
    render(
      <AgentRouteProvider agentId="tco" defaultPage="portfolio">
        <Probe />
      </AgentRouteProvider>,
    );
    expect(screen.getAllByTestId('where')[1]).toHaveTextContent('portfolio|{}');
  });

  it('refuses to be used outside a provider', () => {
    expect(() => render(<Probe />)).toThrow(/AgentRouteProvider/);
  });
});
