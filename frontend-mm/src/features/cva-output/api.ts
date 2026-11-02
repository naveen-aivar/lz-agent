import { agentApiBase } from '@/shared/api/agent-api';
import { idToken } from '@/shared/auth/cognito';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function authHeader(): Promise<Record<string, string>> {
  try {
    const token = await idToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

/** Calls the processing service. Paths are the ones the service already uses, under this agent's API. */
export async function cvaRequest<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = await authHeader();
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(`${agentApiBase('cva-output')}/api${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      credentials: 'omit',
    });
  } catch {
    throw new ApiError(0, 'Could not reach the processing service. Check your connection.');
  }
  // The service answers { error: "..." }; the dashboard's key gate answers { error: { code, message } }.
  let data: { error?: string | { message?: string } } | null = null;
  try {
    data = (await response.json()) as { error?: string | { message?: string } };
  } catch {
    data = null;
  }
  if (!response.ok) {
    if (response.status === 401) throw new ApiError(401, 'Sign in again to use this.');
    const message = typeof data?.error === 'string' ? data.error : data?.error?.message;
    throw new ApiError(response.status, message || `The request failed (${response.status}).`);
  }
  return data as T;
}

export async function fileToB64(file: File): Promise<{ name: string; b64: string }> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return { name: file.name, b64: btoa(binary) };
}
