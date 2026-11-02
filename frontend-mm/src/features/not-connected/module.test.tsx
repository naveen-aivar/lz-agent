import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { notConnectedModule } from '@/features/not-connected/module';

describe('the stand-in for an agent that is not connected yet', () => {
  it('names the agent and says its screens are not there yet', () => {
    const agentModule = notConnectedModule('tco');
    const Screen = agentModule.Screen;
    render(<Screen route={{ page: agentModule.defaultPage, params: {} }} navigate={() => {}} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByText('TCO Agent is not connected yet')).toBeInTheDocument();
  });

  it('offers nothing to press', () => {
    const agentModule = notConnectedModule('mra');
    const Screen = agentModule.Screen;
    render(<Screen route={{ page: agentModule.defaultPage, params: {} }} navigate={() => {}} />);
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('has one page, which is the one that opens first', () => {
    const agentModule = notConnectedModule('seven-rs');
    expect(agentModule.id).toBe('seven-rs');
    expect(agentModule.nav.flatMap((section) => section.items).map((item) => item.id)).toEqual([agentModule.defaultPage]);
    expect(agentModule.titleOf({ page: agentModule.defaultPage, params: {} })).toBe('Overview');
  });
});
