import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Handover } from '@/features/orchestrator/api';
import { RunDetail } from '@/features/orchestrator/run-detail';
import { RunList } from '@/features/orchestrator/run-list';
import { GenerateDecks, optionText } from '@/features/orchestrator/trigger-form';
import { EMPTY_TRIGGER, planRun, type TriggerForm } from '@/features/orchestrator/trigger';

const A = 'a'.repeat(32);
const B = 'b'.repeat(32);
const form = (over: Partial<TriggerForm>): TriggerForm => ({ ...EMPTY_TRIGGER, ...over });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const handover = (job_id: string, sources: Handover['sources'], customer: string | null = null): Handover => ({ job_id, created_at: '2026-10-30T01:00:00Z', customer, sources });
const TCO = { complete: true, files: [{ slot: 'tco.aggregated', filename: 'aggregated_output.json', size: 70938 }] };
const MRA = { complete: true, files: [{ slot: 'mra.file', filename: 'readout.pptx', size: 6596397 }] };

afterEach(() => vi.unstubAllGlobals());

describe('the trigger plan', () => {
  it('needs a deck, a job, and a customer or an MRA job', () => {
    expect(planRun(form({ decks: [] }))).toEqual({ error: 'Choose at least one deck.' });
    expect(planRun(form({}))).toEqual({ error: 'Choose the job to use for at least one source.' });
    expect(planRun(form({ picked: { tco: A } }))).toEqual({ error: 'Enter the customer name, or choose an MRA job, which names the customer.' });
  });
  it('refuses a job id that is not 32 letters and digits, and a date that is not a date', () => {
    expect(planRun(form({ customer: 'Acme', picked: { tco: 'abc' } }))).toEqual({ error: 'TCO: the job id must be 32 letters and digits.' });
    expect(planRun(form({ customer: 'Acme', date: '28/10/2026', picked: { tco: A } }))).toEqual({ error: 'The date must look like 2026-10-28.' });
  });
  it('sends the chosen jobs by source, nothing for a source left out, and lists what the decks could still use', () => {
    expect(planRun(form({ picked: { tco: A, mra: B, sevenrs: '' } }))).toEqual({
      plan: { request: { decks: ['map_assess', 'cva'], from_jobs: { tco: A, mra: B } }, missingSources: ['7Rs', 'CVA'] },
    });
    expect(planRun(form({ customer: ' Acme ', date: '2026-10-30', decks: ['map_assess'], picked: { tco: A } }))).toMatchObject({
      plan: { request: { customer: 'Acme', date: '2026-10-30', decks: ['map_assess'], from_jobs: { tco: A } }, missingSources: ['7Rs', 'MRA'] },
    });
  });
  it('refuses jobs that none of the chosen decks uses', () => {
    expect(planRun(form({ decks: ['map_assess'], customer: 'Acme', picked: { cva: A } }))).toEqual({
      error: 'None of the chosen jobs is used by the decks you chose. Choose a job for a source the decks use.',
    });
  });
});

describe('the choices', () => {
  it('starts each with the job id, then when it came, the customer and the files', () => {
    const text = optionText(handover(A, { tco: TCO }, 'Acme'), 'tco');
    expect(text.startsWith(A)).toBe(true);
    expect(text).toContain('Acme');
    expect(text).toContain('aggregated_output.json (69.3 KB)');
  });
});

describe('the screens', () => {
  it('says there are no decks yet', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ jobs: [], next_cursor: null })));
    render(<RunList navigate={() => {}} />);
    expect(await screen.findByText(/No decks yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate decks' })).toBeEnabled();
  });

  it('shows a plain message when the service refuses the call', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({}, 401)));
    render(<RunList navigate={() => {}} />);
    expect(await screen.findByText('Sign in again to use this.')).toBeInTheDocument();
  });

  it('has no upload field, lists the jobs by source, and starts the run from the chosen ids', async () => {
    const calls: { path: string; body?: unknown }[] = [];
    const navigate = vi.fn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = String(url).replace(/^.*\/api/, '');
        calls.push({ path: `${init?.method ?? 'GET'} ${path}`, body: init?.body ? JSON.parse(String(init.body)) : undefined });
        if (path === '/handovers') return json({ handovers: [handover(A, { tco: TCO }, 'Acme'), handover(B, { mra: MRA, tco: { complete: false, files: [] } })] });
        if (path === '/jobs') return json({ job_id: 'c'.repeat(32), status: 'CREATED', decks: ['map_assess'], uploads: [] }, 201);
        return json({ job_id: 'c'.repeat(32), status: 'QUEUED', decks: ['map_assess'] }, 202);
      }),
    );
    const user = userEvent.setup();
    const { container } = render(<GenerateDecks navigate={navigate} />);
    await waitFor(() => expect(screen.getByLabelText(/^TCO/)).toBeEnabled());
    expect(container.querySelector('input[type="file"]')).toBeNull();
    const tco = screen.getByLabelText(/^TCO/);
    expect(within(tco).getAllByRole('option').map((option) => option.textContent?.slice(0, 8))).toEqual(['Not incl', 'aaaaaaaa', 'bbbbbbbb']);
    expect(within(tco).getByRole('option', { name: new RegExp(`^${B}.*incomplete`) })).toBeDisabled();
    await user.selectOptions(tco, A);
    await user.selectOptions(screen.getByLabelText(/^MRA/), B);
    await user.click(screen.getByRole('checkbox', { name: /^CVA/ }));
    await user.click(screen.getByRole('button', { name: 'Generate decks' }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('run', { id: 'c'.repeat(32) }));
    expect(calls.map((call) => call.path)).toEqual(['GET /handovers', 'POST /jobs', `POST /jobs/${'c'.repeat(32)}/start`]);
    expect(calls[1].body).toEqual({ decks: ['map_assess'], from_jobs: { tco: A, mra: B } });
  });

  it('says so when no agent has handed anything over yet', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ handovers: [] })));
    render(<GenerateDecks navigate={() => {}} />);
    await waitFor(() => expect(screen.getByLabelText(/^TCO/)).toBeEnabled());
    expect(within(screen.getByLabelText(/^TCO/)).getByRole('option', { name: 'No jobs yet' })).toBeInTheDocument();
  });

  it('shows a finished deck with its downloads, the slides that had no data and the jobs it was built from', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).endsWith('/outputs')) {
          return json({ decks: [{ deck: 'map_assess', name: 'MAP Assess', files: { pptx: { url: 'https://x.example/a.pptx', filename: 'a.pptx' }, pdf: { url: 'https://x.example/a.pdf', filename: 'a.pdf' } } }] });
        }
        return json({
          job_id: 'j1', status: 'COMPLETED', customer: 'Acme', decks: ['map_assess'], created_at: '2026-10-30T01:00:00Z', source_jobs: { tco: A },
          results: [{ deck: 'map_assess', name: 'MAP Assess', available: ['pptx', 'pdf'], warnings: [], slides: [{ no: 1, title: 'Cover', status: 'code' }, { no: 2, title: 'Readiness', status: 'unavailable', reason: 'no MRA file' }] }],
          events: [],
        });
      }),
    );
    render(<RunDetail id="j1" />);
    expect(await screen.findByText('MAP Assess')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('link', { name: /Download PowerPoint/ })).toHaveAttribute('href', 'https://x.example/a.pptx'));
    expect(screen.getByText('2 slides, 1 without data or not built')).toBeInTheDocument();
    expect(screen.getByText(`Built from: TCO ${A}`)).toBeInTheDocument();
  });

  it('says why a failed run failed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ job_id: 'j2', status: 'FAILED', decks: ['cva'], error: { code: 'BAD_REQUEST', message: 'No customer name.' } })));
    render(<RunDetail id="j2" />);
    expect(await screen.findByText('No customer name.')).toBeInTheDocument();
  });
});
