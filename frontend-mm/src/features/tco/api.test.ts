import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/shared/auth/cognito', () => ({ idToken: async () => 'signed-in-token' }));

import { TcoClient } from '@/features/tco/api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('TCO calls', () => {
  it('sends the sign-in token and does not send an access key', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ data: [], next_cursor: null }), { status: 200 }));
    const client = new TcoClient(fetchImpl);
    await client.listJobs();
    const call = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(call[1].headers);
    expect(headers.get('Authorization')).toBe('Bearer signed-in-token');
    expect(headers.get('X-Access-Key')).toBeNull();
  });
});
