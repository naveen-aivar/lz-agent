import { describe, expect, it, vi } from "vitest";
import { ApiError, createClient, SessionExpired } from "./client";

const reply = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status }));
const make = (fetchImpl: typeof fetch, token: string | null = "tok") => {
  const onExpired = vi.fn();
  return { onExpired, client: createClient({ apiUrl: "https://api.example", getToken: () => token, onExpired, fetchImpl }) };
};

describe("api client", () => {
  it("sends the token as is and unwraps {data}", async () => {
    const f = vi.fn(() => reply(200, { data: { runs: [] } }));
    const { client } = make(f as unknown as typeof fetch);
    expect(await client.listRuns()).toEqual({ runs: [] });
    expect(f).toHaveBeenCalledWith("https://api.example/runs", expect.objectContaining({ method: "GET", headers: expect.objectContaining({ authorization: "tok" }) }));
  });
  it("posts JSON bodies to the typed routes", async () => {
    const f = vi.fn(() => reply(200, { data: { pendingDecision: {} } }));
    const { client } = make(f as unknown as typeof fetch);
    await client.decideTask("r1", { jobId: "j", taskId: "t", decision: "approve" });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example/runs/r1/decision");
    expect(JSON.parse(String(init.body))).toEqual({ jobId: "j", taskId: "t", decision: "approve" });
  });
  it("throws the envelope's code, message and details", async () => {
    const { client } = make((() => reply(409, { error: { code: "conflict", message: "the question has changed", details: { x: 1 } } })) as unknown as typeof fetch);
    await expect(client.getRun("r")).rejects.toMatchObject({ name: "ApiError", status: 409, code: "conflict", message: "the question has changed", details: { x: 1 } });
  });
  it("does not guess when the body is not an envelope", async () => {
    const { client } = make((() => reply(500, { message: "x" })) as unknown as typeof fetch);
    await expect(client.getRun("r")).rejects.toMatchObject({ code: "bad_response" });
    const { client: c2 } = make((() => reply(200, { runs: [] })) as unknown as typeof fetch);
    await expect(c2.listRuns()).rejects.toBeInstanceOf(ApiError);
    const { client: c3 } = make((() => Promise.resolve(new Response("<html>", { status: 502 }))) as unknown as typeof fetch);
    await expect(c3.listRuns()).rejects.toMatchObject({ code: "bad_response", status: 502 });
  });
  it("signals an expired session for a missing token or a 401", async () => {
    const f = vi.fn();
    const none = make(f as unknown as typeof fetch, null);
    await expect(none.client.listRuns()).rejects.toBeInstanceOf(SessionExpired);
    expect(none.onExpired).toHaveBeenCalled();
    expect(f).not.toHaveBeenCalled();
    const unauthorised = make((() => reply(401, { message: "Unauthorized" })) as unknown as typeof fetch);
    await expect(unauthorised.client.listRuns()).rejects.toBeInstanceOf(SessionExpired);
    expect(unauthorised.onExpired).toHaveBeenCalled();
  });
  it("posts a resume with an empty body by default", async () => {
    const f = vi.fn(() => reply(202, { data: { runId: "r1" } }));
    const { client } = make(f as unknown as typeof fetch);
    expect(await client.resumeRun("r1")).toEqual({ runId: "r1" });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example/runs/r1/resume");
    expect(JSON.parse(String(init.body))).toEqual({});
  });
  it("encodes path parameters", async () => {
    const f = vi.fn(() => reply(200, { data: { audit: [] } }));
    const { client } = make(f as unknown as typeof fetch);
    await client.getAudit("a/b");
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe("https://api.example/runs/a%2Fb/audit");
  });
});
