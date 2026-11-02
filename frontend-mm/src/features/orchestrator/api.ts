import { agentApiBase } from '@/shared/api/agent-api';
import { idToken } from '@/shared/auth/cognito';

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** A job that holds files handed over by the assessment agents. A deck run is built from these, chosen by job id. */
export interface Handover {
  job_id: string;
  created_at: string;
  customer?: string | null;
  sources: Record<string, { complete: boolean; files: { slot: string; filename: string; size: number }[] }>;
}

export interface SlideResult {
  no: number;
  title: string;
  status: 'built' | 'code' | 'unavailable' | 'failed' | string;
  reason?: string;
}

export interface DeckResult {
  deck: string;
  name: string;
  available: string[];
  slides: SlideResult[];
  warnings: string[];
}

export interface RunEvent {
  ts: string;
  stage?: string;
  message: string;
}

export interface Run {
  job_id: string;
  status: 'CREATED' | 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | string;
  customer?: string | null;
  date?: string;
  decks: string[];
  created_at?: string;
  updated_at?: string;
  stalled?: boolean;
  inputs?: string[];
  source_jobs?: Record<string, string>;
  input_problems?: Record<string, string>;
  results?: DeckResult[];
  error?: { code: string; message: string } | null;
  events?: RunEvent[];
}

export interface DeckFiles {
  deck: string;
  name: string;
  files: Partial<Record<'pptx' | 'pdf', { url: string; filename: string }>>;
}

export interface Outputs {
  decks: DeckFiles[];
  report?: { url: string };
}

export interface CreateRunRequest {
  customer?: string;
  decks: string[];
  date?: string;
  /** Source to the id of the job that holds its files, for example { tco: "<job id>" }. */
  from_jobs: Record<string, string>;
}

/** Calls the deck orchestrator through the dashboard. The access key is added after sign-in, on the server. */
export class OrchestratorClient {
  constructor(private readonly fetchImpl: typeof fetch = (...args) => fetch(...args)) {}

  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const headers: Record<string, string> = {};
    try {
      const token = await idToken();
      if (token) headers.Authorization = `Bearer ${token}`;
    } catch {
      /* no session: the gate answers 401 and the page asks the person to sign in again */
    }
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let response: Response;
    try {
      response = await this.fetchImpl(`${agentApiBase('orchestrator')}/api${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
        credentials: 'omit',
      });
    } catch {
      throw new ApiError(0, 'NETWORK', 'Could not reach the deck service. Check your connection.');
    }
    let data: { error?: { code?: string; message?: string } } | null = null;
    try {
      data = (await response.json()) as { error?: { code?: string; message?: string } };
    } catch {
      data = null;
    }
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) throw new ApiError(response.status, 'UNAUTHORIZED', 'Sign in again to use this.');
      if (response.status === 404 && !data?.error) throw new ApiError(404, 'NOT_CONNECTED', 'The deck service is not connected to this dashboard yet.');
      throw new ApiError(response.status, data?.error?.code ?? 'ERROR', data?.error?.message ?? `The request failed (${response.status}).`);
    }
    return data;
  }

  listRuns(query: { limit?: number; cursor?: string | null } = {}) {
    const params = new URLSearchParams();
    if (query.limit) params.set('limit', String(query.limit));
    if (query.cursor) params.set('cursor', query.cursor);
    const suffix = params.toString();
    return this.request('GET', `/jobs${suffix ? `?${suffix}` : ''}`) as Promise<{ jobs: Run[]; next_cursor: string | null }>;
  }

  handovers() {
    return this.request('GET', '/handovers') as Promise<{ handovers: Handover[] }>;
  }

  createRun(payload: CreateRunRequest) {
    return this.request('POST', '/jobs', payload) as Promise<Run>;
  }

  startRun(id: string) {
    return this.request('POST', `/jobs/${encodeURIComponent(id)}/start`) as Promise<Run>;
  }

  getRun(id: string) {
    return this.request('GET', `/jobs/${encodeURIComponent(id)}`) as Promise<Run>;
  }

  outputs(id: string) {
    return this.request('GET', `/jobs/${encodeURIComponent(id)}/outputs`) as Promise<Outputs>;
  }
}

export const orchestratorApi = new OrchestratorClient();
