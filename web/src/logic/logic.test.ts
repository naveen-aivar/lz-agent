import { describe, expect, it, vi } from "vitest";
import type { AuditItem, Run, RunSummary } from "../api/client";
import { parseScope } from "./design";
import { MAX_SOW_BYTES, isPresignedPost, newRunError, uploadSow } from "./newrun";
import { pauseNotice } from "./notices";
import { gapSummary, parseDeploymentReport, parseValidationReport } from "./reports";
import { countByStatus, filterRuns, needsAttention, slug } from "./runs";
import { designSteps } from "./steps";
const r = (o: Partial<RunSummary>): RunSummary => ({ runId: "ab".repeat(16), customerId: "acme-co", status: "DELIVERED", createdAt: 1, runKind: null, error: "", ...o });
describe("runs", () => {
  const runs = [r({}), r({ runId: "c".repeat(32), runKind: "deploy", status: "RUNNING", awaitingHitl: true }), r({ runId: "d".repeat(32), runKind: "deploy", status: "FAILED", customerId: "zeta" })];
  it("filters by state, type and text", () => {
    expect(filterRuns(runs, { status: "attention", kind: "all", query: "" }).map((x) => x.runId[0])).toEqual(["c"]);
    expect(filterRuns(runs, { status: "all", kind: "design", query: "" })).toHaveLength(1);
    expect(filterRuns(runs, { status: "all", kind: "all", query: "ZETA" })).toHaveLength(1);
    expect(filterRuns(runs, { status: "all", kind: "all", query: "dddd" })).toHaveLength(1);
    expect(filterRuns(runs, { status: "failed", kind: "design", query: "" })).toHaveLength(0);
  });
  it("counts each state and flags only running runs that wait for a person", () => {
    expect(countByStatus(runs)).toEqual({ all: 3, attention: 1, active: 1, failed: 1, delivered: 1 });
    expect(needsAttention(r({ status: "FAILED", awaitingHitl: true }))).toBe(false);
  });
  it("makes a run name the API accepts", () => {
    expect(slug("  Moon Trades, Inc. ")).toBe("moon-trades-inc");
    expect(slug("x".repeat(60))).toHaveLength(40);
  });
});
describe("newRunError", () => {
  const ok = { customer: "Moon Trades", requirements: "", file: { name: "sow.pdf", size: 10 } };
  it("accepts a good form", () => expect(newRunError(ok)).toBeNull());
  it("names each problem", () => {
    expect(newRunError({ ...ok, customer: "a!" })).toMatch(/customer's name/);
    expect(newRunError({ ...ok, file: null })).toMatch(/SOW file/);
    expect(newRunError({ ...ok, file: null, requirements: "text" })).toBeNull();
    expect(newRunError({ ...ok, file: { name: "x.exe", size: 1 } })).toMatch(/isn't supported/);
    expect(newRunError({ ...ok, file: { name: "x.pdf", size: MAX_SOW_BYTES + 1 } })).toMatch(/10 MB/);
  });
});
describe("uploadSow", () => {
  it("posts the fields first and the file last, and names a failed status", async () => {
    const f = vi.fn().mockResolvedValue({ ok: true });
    await uploadSow({ url: "https://s3.example/x", fields: { key: "k", policy: "p" } }, new Blob(["x"]), f as unknown as typeof fetch);
    const body = f.mock.calls[0]![1].body as FormData;
    expect([...body.keys()]).toEqual(["key", "policy", "file"]);
    await expect(uploadSow({ url: "u", fields: {} }, new Blob([]), (async () => ({ ok: false, status: 403 })) as unknown as typeof fetch)).rejects.toThrow("HTTP 403");
  });
  it("recognises a presigned post", () => {
    expect(isPresignedPost({ url: "u", fields: {} })).toBe(true);
    expect(isPresignedPost(null)).toBe(false);
    expect(isPresignedPost({ url: "u" })).toBe(false);
  });
});
describe("parsers name what is missing", () => {
  it("scope", () => {
    expect(() => parseScope({})).toThrow("customer.orgName");
    expect(() => parseScope(null)).toThrow("its content");
  });
  it("reports", () => {
    expect(() => parseValidationReport({ overall: "pass" })).toThrow("validation report is missing");
    expect(() => parseDeploymentReport({})).toThrow("no overall result");
    expect(parseDeploymentReport({ overall: "pass" }).overall).toBe("pass");
  });
  it("gap summary", () => {
    expect(gapSummary(undefined)).toBe("None listed");
    expect(gapSummary({ missingOus: ["a"], missingAccountsByName: ["b", "c"] })).toBe("1 missing OU(s), 2 missing account name(s)");
    expect(gapSummary({})).toMatch(/No missing/);
  });
});
const ev = (action: string, detail?: object): AuditItem => ({ SK: action, ts: 1, action, actor: "system", detail: detail ? JSON.stringify(detail) : undefined });
describe("designSteps", () => {
  it("marks finished steps and the one in progress", () => {
    const s = designSteps({ runId: "x", status: "RUNNING" } as Run, [ev("sow.extracted")]);
    expect(s.map((x) => x.state)).toEqual(["done", "active", "", ""]);
    expect(designSteps({ runId: "x", status: "FAILED" } as Run, [ev("sow.extracted")])[1]!.state).toBe("failed");
  });
});
describe("pauseNotice", () => {
  const run = { runId: "x", status: "RUNNING", runKind: "deploy" } as Run;
  it("says nothing for routine Transform waits", () => {
    expect(pauseNotice([ev("phase.continue", { reason: "transform_analyze_waiting" })], run)).toBeNull();
    expect(pauseNotice([], run)).toBeNull();
  });
  it("names a platform permission problem", () => {
    const n = pauseNotice([ev("phase.continue", { reason: "AccessDenied on s3:PutObject" })], run);
    expect(n?.title).toMatch(/platform setup/);
  });
  it("explains a wait on Transform", () => {
    expect(pauseNotice([ev("phase.continue", { reason: "needs input", awaitingHitl: true })], run)?.title).toMatch(/Waiting on AWS Transform/);
  });
});
