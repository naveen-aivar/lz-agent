import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/features/mra/api', () => ({
  mraRequest: vi.fn(async (method: string, path: string) => {
    if (path === '/runs') return { runs: [{ customer: 'Northwind', set_id: 'RUN-1', final: false, blank_ratings: 2, engine: 'stub', generated_at: '2026-10-28T00:00:00+00:00' }] };
    return {};
  }),
  ApiError: class ApiError extends Error { status = 0; },
}));

import { RunsScreen } from '@/features/mra/runs';

describe('the readiness run list', () => {
  it('shows the runs the service returned', async () => {
    render(<RunsScreen navigate={() => {}} />);
    expect(await screen.findByText('Northwind')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open' })).toBeInTheDocument();
    expect(screen.queryByText('Dashboard')).not.toBeInTheDocument();
  });
});
