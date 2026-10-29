import type { components } from "./schema";

export type Schemas = components["schemas"];
export type Run = Schemas["Run"];
export type RunSummary = Schemas["RunSummary"];
export type PendingHumanInput = Schemas["PendingHumanInput"];
export type AgentNote = Schemas["AgentNote"];
export type AuditItem = Schemas["AuditItem"];
export type PendingAnswer = Schemas["PendingAnswer"];
export type PendingDecision = Schemas["PendingDecision"];
export type DeployRequest = Schemas["DeployRequest"];
export type AnswerRequest = Schemas["AnswerRequest"];
export type VerifyData = Schemas["VerifyData"];

/** An error envelope from the API: {error: {code, message, details?}}. */
export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string, readonly details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
  }
}

/** The ID token is missing or expired: the user has to sign in again. */
export class SessionExpired extends Error {
  constructor() {
    super("session expired");
    this.name = "SessionExpired";
  }
}

export interface ClientOptions {
  apiUrl: string;
  getToken: () => string | null;
  onExpired: () => void;
  fetchImpl?: typeof fetch;
}

export type Client = ReturnType<typeof createClient>;

export function createClient({ apiUrl, getToken, onExpired, fetchImpl = fetch }: ClientOptions) {
  async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    const token = getToken();
    if (!token) {
      onExpired();
      throw new SessionExpired();
    }
    const r = await fetchImpl(apiUrl + path, {
      method,
      headers: { authorization: token, "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (r.status === 401) {
      onExpired();
      throw new SessionExpired();
    }
    let payload: unknown;
    try {
      payload = await r.json();
    } catch {
      throw new ApiError(r.status, "bad_response", `the API answered HTTP ${r.status} without JSON`);
    }
    const env = payload as { data?: T; error?: { code: string; message: string; details?: Record<string, unknown> } };
    if (!r.ok) {
      if (!env.error) throw new ApiError(r.status, "bad_response", `the API answered HTTP ${r.status} without an error envelope`);
      throw new ApiError(r.status, env.error.code, env.error.message, env.error.details);
    }
    if (env.data === undefined) throw new ApiError(r.status, "bad_response", "the API response has no data");
    return env.data;
  }

  const enc = encodeURIComponent;
  return {
    listRuns: () => request<Schemas["RunsData"]>("GET", "/runs"),
    getRun: (runId: string) => request<Schemas["RunData"]>("GET", `/runs/${enc(runId)}`),
    getAudit: (runId: string) => request<Schemas["AuditData"]>("GET", `/runs/${enc(runId)}/audit`),
    getScope: (runId: string) => request<Schemas["ScopeData"]>("GET", `/runs/${enc(runId)}/scope`),
    startDeploy: (designRunId: string, body: DeployRequest) =>
      request<Schemas["RunIdData"]>("POST", `/runs/${enc(designRunId)}/deploy`, body),
    stopRun: (runId: string) => request<Schemas["StoppedData"]>("POST", `/runs/${enc(runId)}/stop`),
    answerQuestion: (runId: string, body: AnswerRequest) =>
      request<Schemas["PendingAnswerData"]>("POST", `/runs/${enc(runId)}/answer`, body),
    decideTask: (runId: string, body: Schemas["DecisionRequest"]) =>
      request<Schemas["PendingDecisionData"]>("POST", `/runs/${enc(runId)}/decision`, body),
    verifyDeployTarget: (body: Schemas["VerifyRequest"]) =>
      request<Schemas["VerifyData"]>("POST", "/deploy-target/verify", body),
  };
}
