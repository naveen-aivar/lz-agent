import { agentApiBase } from '@/shared/api/agent-api';
import { idToken } from '@/shared/auth/cognito';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const root = () => `${agentApiBase('mra')}/api`;

/** The service returns paths on its own site. Through the portal they must stay under this agent's API. */
export function mraUrl(path: string): string {
  if (path.startsWith('/api/')) return `${agentApiBase('mra')}${path}`;
  return path;
}

async function authHeader(): Promise<Record<string, string>> {
  try {
    const token = await idToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

function messageOf(data: { error?: string; errors?: string[] } | null, status: number): string {
  if (data?.errors?.length) return data.errors.join('; ');
  if (data?.error) return data.error;
  if (status === 401) return 'Sign in again to use this.';
  if (status === 404) return 'That readiness run is not on the service.';
  return `The request failed (${status}).`;
}

async function read(response: Response): Promise<{ error?: string; errors?: string[]; job_id?: string; state?: string; result?: unknown; payload?: { error?: string; errors?: string[] } }> {
  try {
    return (await response.json()) as { error?: string; errors?: string[]; job_id?: string };
  } catch {
    return {};
  }
}

/** Calls the readiness service. A slow task comes back as a job; this waits for it. */
export async function mraRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = await authHeader();
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(`${root()}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      credentials: 'omit',
    });
  } catch {
    throw new ApiError(0, 'Could not reach the readiness service. Check your connection.');
  }
  const data = await read(response);
  if (response.status === 202 && data.job_id) return pollJob<T>(data.job_id);
  if (!response.ok) throw new ApiError(response.status, messageOf(data, response.status));
  return data as T;
}

async function pollJob<T>(jobId: string): Promise<T> {
  const started = Date.now();
  let delay = 1000;
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(delay * 1.4, 4000);
    const response = await fetch(`${root()}/jobs/${jobId}`, { headers: await authHeader(), cache: 'no-store' });
    const job = (await response.json()) as { state: string; result: T; payload?: { error?: string; errors?: string[] }; status?: number };
    if (!response.ok) throw new ApiError(response.status, 'The task could not be checked.');
    if (job.state === 'done') return job.result;
    if (job.state === 'failed') {
      const payload = job.payload;
      throw new ApiError(job.status ?? 500, payload?.error || payload?.errors?.join('; ') || 'The task failed.');
    }
    if (Date.now() - started > 16 * 60 * 1000) throw new ApiError(0, 'This is taking too long. Open the run again in a few minutes.');
  }
}

export async function uploadFile(file: File, purpose: string): Promise<string> {
  const ticket = await mraRequest<{ upload_id: string; mode: string; url: string; fields?: Record<string, string> }>('POST', '/uploads', {
    purpose,
    name: file.name,
    size: file.size,
  });
  if (ticket.mode === 'put') {
    const response = await fetch(mraUrl(ticket.url), { method: 'PUT', headers: await authHeader(), body: file });
    if (!response.ok) throw new ApiError(response.status, 'The upload failed.');
  } else {
    const form = new FormData();
    for (const [key, value] of Object.entries(ticket.fields ?? {})) form.append(key, value);
    form.append('file', file);
    const response = await fetch(ticket.url, { method: 'POST', body: form });
    if (!response.ok) throw new ApiError(response.status, 'The upload to storage failed. Try again.');
  }
  return ticket.upload_id;
}

export async function fileToB64(file: File): Promise<string> {
  const data = await file.arrayBuffer();
  const bytes = new Uint8Array(data);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
