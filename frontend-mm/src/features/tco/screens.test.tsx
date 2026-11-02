import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AssessmentDetail, AssessmentList } from '@/features/tco/screens';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the assessment list', () => {
  it('says there are none when the service returns an empty page', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ data: [], next_cursor: null }), { status: 200, headers: { 'Content-Type': 'application/json' } })),
    );
    render(<AssessmentList navigate={() => {}} />);
    expect(await screen.findByText('No assessments yet.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New assessment' })).toBeEnabled();
  });

  it('keeps the headings and shows fifteen rows while the list is loading', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => undefined)));
    render(<AssessmentList navigate={() => {}} />);
    expect(screen.getByRole('heading', { name: 'Assessments' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New assessment' })).toBeDisabled();
    expect(screen.getAllByText('inventory-export.xlsx')).toHaveLength(15);
    expect(screen.getByRole('columnheader', { name: 'File' })).toBeInTheDocument();
  });
});

describe('an open assessment', () => {
  it('loads a finished assessment once, including its files, and does not keep asking', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).endsWith('/outputs')) {
          return new Response(JSON.stringify({ files: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        return new Response(
          JSON.stringify({ job_id: 'j1', status: 'COMPLETED', original_filename: 'servers.xlsx', created_at: '2026-10-28T11:00:00Z', summary: { pricing_models: [] } }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );
    render(<AssessmentDetail id="j1" />);
    expect(await screen.findByRole('heading', { name: 'servers.xlsx' })).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 50));
    const calls = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls.map((call) => String(call[0]));
    expect(calls.filter((url) => url.includes('/jobs/j1') && !url.includes('/outputs'))).toHaveLength(1);
    expect(calls.filter((url) => url.includes('/outputs'))).toHaveLength(1);
  });

  it('shows each file as a card with download, and the activity as a timeline', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).endsWith('/outputs')) {
          return new Response(
            JSON.stringify({
              files: [
                { label: 'deck_pdf', filename: 'deck.pdf', url: 'https://example.com/deck.pdf' },
                { label: 'summary', filename: 'summary.xlsx', url: 'https://example.com/summary.xlsx' },
              ],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response(
          JSON.stringify({
            job_id: 'j1',
            status: 'COMPLETED',
            original_filename: 'servers.xlsx',
            created_at: '2026-10-28T11:00:00Z',
            summary: { pricing_models: [] },
            events: [{ ts: '2026-10-28T11:01:00Z', message: 'Read the inventory.' }],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }),
    );
    render(<AssessmentDetail id="j1" />);
    await screen.findByRole('heading', { name: 'servers.xlsx' });
    await userEvent.click(screen.getByRole('tab', { name: 'Downloads' }));
    expect(screen.getAllByRole('link', { name: 'Download' })).toHaveLength(2);
    const previews = screen.getAllByRole('button', { name: 'Preview' });
    expect(previews[0]).toBeEnabled();
    expect(previews[1]).toBeDisabled();
    await userEvent.click(screen.getByRole('tab', { name: 'Timeline' }));
    expect(screen.getByRole('list', { name: 'What the assessment has done' })).toBeInTheDocument();
    expect(screen.getByText('Read the inventory.')).toBeInTheDocument();
  });
});
