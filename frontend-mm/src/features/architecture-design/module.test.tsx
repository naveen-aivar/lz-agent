import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import agent from '@/features/architecture-design/module';

// The dashboard's key gate holds the agent's access key; the screens send the signed-in person's ID token.
vi.mock('@/shared/auth/cognito', () => ({ idToken: vi.fn(async () => 'id-token-1') }));

describe('Architecture Design in the dashboard', () => {
  it('sends the signed-in person’s token, never an access key, and asks no key when refused', async () => {
    const seen: Headers[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        seen.push(new Headers(init?.headers));
        return new Response(JSON.stringify({ error: { code: 'UNAUTHORIZED', message: 'Sign in again to use this.' } }), { status: 401 });
      }),
    );
    const { Provider, Screen } = agent;
    if (!Provider) throw new Error('missing provider');
    render(
      <Provider>
        <Screen route={{ page: 'runs', params: {} }} navigate={() => {}} />
      </Provider>,
    );
    expect(await screen.findByText(/Sign in again/)).toBeInTheDocument();
    expect(seen.length).toBeGreaterThan(0);
    for (const headers of seen) {
      expect(headers.get('Authorization')).toBe('Bearer id-token-1');
      expect(headers.get('X-Access-Key')).toBeNull();
    }
    expect(screen.queryByLabelText('Access key', { selector: 'input' })).toBeNull();
  });

  it('draws the runs page inside the dashboard, not a second shell', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path.endsWith('/runs')) return new Response(JSON.stringify({ runs: [] }), { status: 200 });
        if (path.endsWith('/session')) return new Response(JSON.stringify({ ok: true, runs_today: 0, runs_per_day: 40 }), { status: 200 });
        return new Response('{}', { status: 404 });
      }),
    );
    const { Provider, Screen } = agent;
    if (!Provider) throw new Error('missing provider');
    const { container } = render(
      <Provider>
        <Screen route={{ page: 'runs', params: {} }} navigate={() => {}} />
      </Provider>,
    );
    expect(await screen.findByRole('heading', { name: 'Runs' })).toBeInTheDocument();
    const screenRoot = container.querySelector('#content');
    const portal = container.querySelector('#mm-architecture-design-portal');
    expect(screenRoot?.classList.contains('mm-architecture-design')).toBe(true);
    expect(screenRoot?.parentElement).toBe(container);
    expect(portal?.parentElement).toBe(container);
  });

  it('shows the runs once the list resolves, even though Screen sits inside Provider as a fixed `children` element', async () => {
    // The dashboard mounts Screen as Provider's `children` once and never recreates that element on Provider's own
    // poll ticks (see module.tsx). If the run list were only shared through a plain mutable object instead of
    // context, React would skip re-rendering this `children` subtree and the table would stay on its skeleton
    // forever, even after the fetch below resolves. This reproduces that exact shape.
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path.endsWith('/runs')) return new Response(JSON.stringify({ runs: [{ run_id: 'r1', title: 'My architecture', status: 'succeeded' }] }), { status: 200 });
        if (path.endsWith('/session')) return new Response(JSON.stringify({ ok: true, runs_today: 0, runs_per_day: 40 }), { status: 200 });
        return new Response('{}', { status: 404 });
      }),
    );
    const { Provider, Screen } = agent;
    if (!Provider) throw new Error('missing provider');
    const children = <Screen route={{ page: 'runs', params: {} }} navigate={() => {}} />;
    render(<Provider>{children}</Provider>);
    expect(await screen.findByText('My architecture')).toBeInTheDocument();
  });
});
