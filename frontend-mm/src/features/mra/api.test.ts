import { afterEach, describe, expect, it, vi } from 'vitest';

import { mraRequest, ApiError } from '@/features/mra/api';

afterEach(() => vi.unstubAllGlobals());

describe('the readiness client', () => {
  it('reads the service error and does not invent one', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'Choose the questionnaire first.' }), { status: 400, headers: { 'content-type': 'application/json' } })));
    await expect(mraRequest('POST', '/runs', {})).rejects.toMatchObject({ message: 'Choose the questionnaire first.', status: 400 });
  });

  it('waits for a queued task and returns its result', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ job_id: 'abc' }), { status: 202, headers: { 'content-type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ state: 'done', result: { set_id: 'RUN-1' } }), { status: 200, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const pending = mraRequest<{ set_id: string }>('POST', '/runs', {});
    await vi.advanceTimersByTimeAsync(1000);
    await expect(pending).resolves.toEqual({ set_id: 'RUN-1' });
    vi.useRealTimers();
  });

  it('says when the service cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
    await expect(mraRequest('GET', '/runs')).rejects.toBeInstanceOf(ApiError);
  });
});
