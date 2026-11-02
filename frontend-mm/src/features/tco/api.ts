import { agentApiBase } from '@/shared/api/agent-api';
import type { LicensingSummary, MapEstimateSummary } from '@/features/tco/licensing';
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

/** Calls the assessment service through the dashboard. The access key is added after sign-in, on the server. */
export class TcoClient {
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
      response = await this.fetchImpl(`${agentApiBase('tco')}/api${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
        credentials: 'omit',
      });
    } catch {
      throw new ApiError(0, 'NETWORK', 'Could not reach the assessment service. Check your connection.');
    }
    let data: { error?: { code?: string; message?: string } } | null = null;
    try {
      data = (await response.json()) as { error?: { code?: string; message?: string } };
    } catch {
      data = null;
    }
    if (!response.ok) {
      if (response.status === 401) throw new ApiError(401, 'UNAUTHORIZED', 'Sign in again to use this.');
      if (response.status === 404) throw new ApiError(404, 'NOT_CONNECTED', 'The assessment service is not connected to this dashboard yet.');
      throw new ApiError(response.status, data?.error?.code ?? 'ERROR', data?.error?.message ?? `The request failed (${response.status}).`);
    }
    return data;
  }

  health() {
    return this.request('GET', '/health') as Promise<{ features?: { map_credits?: string; licensing?: string } }>;
  }

  listJobs(query: { limit?: number; cursor?: string | null } = {}) {
    const params = new URLSearchParams();
    if (query.limit) params.set('limit', String(query.limit));
    if (query.cursor) params.set('cursor', query.cursor);
    const suffix = params.toString();
    return this.request('GET', `/jobs${suffix ? `?${suffix}` : ''}`) as Promise<{ data: Job[]; next_cursor: string | null }>;
  }

  createJob(payload: unknown) {
    return this.request('POST', '/jobs', payload) as Promise<{
      job_id: string;
      upload: { url: string; fields: Record<string, string> };
      statement_upload?: { url: string; fields: Record<string, string> };
    }>;
  }

  startJob(jobId: string) {
    return this.request('POST', `/jobs/${encodeURIComponent(jobId)}/start`);
  }

  getJob(jobId: string) {
    return this.request('GET', `/jobs/${encodeURIComponent(jobId)}`) as Promise<Job>;
  }

  answerJob(jobId: string, answer: unknown) {
    return this.request('POST', `/jobs/${encodeURIComponent(jobId)}/input`, answer);
  }

  jobOutputs(jobId: string) {
    return this.request('GET', `/jobs/${encodeURIComponent(jobId)}/outputs`) as Promise<{ files: OutputFile[] }>;
  }

  async uploadFile(upload: { url: string; fields: Record<string, string> }, file: File) {
    const form = new FormData();
    for (const [name, value] of Object.entries(upload.fields)) form.append(name, value);
    form.append('file', file);
    let response: Response;
    try {
      response = await this.fetchImpl(upload.url, { method: 'POST', body: form });
    } catch {
      throw new ApiError(0, 'UPLOAD_NETWORK', 'The file upload failed. Check your connection.');
    }
    if (!response.ok) throw new ApiError(response.status, 'UPLOAD_FAILED', `The file upload was rejected (${response.status}).`);
  }
}

export interface Job {
  job_id: string;
  status: string;
  original_filename?: string;
  customer_ref?: string;
  created_at?: string;
  updated_at?: string;
  error_message?: string;
  error_code?: string;
  pending_input?: import('@/features/tco/answer').PendingInput;
  summary?: Summary;
  events?: JobEvent[];
}

/** One step of the timeline. `detail.sent` is what was sent to AWS Transform, as key and value. */
export interface JobEvent {
  ts: string;
  message: string;
  detail?: { sent?: Record<string, unknown> } | null;
}
export interface OutputFile {
  label: string;
  filename: string;
  url: string;
}

export interface PricingModel {
  name: string;
  annual_aws_cost: number;
  recommended?: boolean;
}

export interface Summary {
  servers_in_scope?: number;
  servers_total?: number;
  volumes_in_scope?: number;
  volumes_total?: number;
  capacity_description?: string;
  pricing_models: PricingModel[];
  calculator?: { url?: string; estimate_annual?: number; verified?: boolean; reconciling?: Record<string, number>; transform_recommended_annual?: number; unreconciled?: string[]; decisions?: { setting: string; evidence: string }[]; verification?: string; map_estimate?: MapEstimateSummary | null };
  licensing?: LicensingSummary | null;
  handover?: { job_id: string; files?: { slot: string; filename: string; size: number }[]; baseline_removed?: boolean; handed_over_at?: string } | null;
  map?: {
    enrolled?: boolean;
    items?: { service: string; label: string; source: string; percent?: number; credit_annual?: number; applies: string }[];
    transform_credit_annual?: number;
    entered_credit_annual?: number;
    entered_credit_total?: number;
    recommended_annual?: number;
    after_entered_annual?: number;
    warnings?: string[];
  };
}

export const tcoApi = new TcoClient();
