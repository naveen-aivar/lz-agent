import { describe, expect, it } from "vitest";
import type { CustomScp } from "./design";
import { journey, startStep, stepOrDefault } from "./journey";
import { countProjects, filterProjects, groupProjects, stageOf } from "./projects";
import { buildEdits, draftError, draftOf, fillPolicy, isDirty, missingValues, parsePolicy, placeholders, valueError } from "./scps";
import type { RunSummary } from "../api/client";
const r = (o: Partial<RunSummary>): RunSummary => ({ runId: "a".repeat(32), customerId: "acme", status: "DELIVERED", createdAt: 100, runKind: null, error: "", ...o });
describe("groupProjects", () => {
  const design = r({ runId: "d".repeat(32), createdAt: 10 });
  it("puts a design run and its newest deploy run in one row", () => {
    const old = r({ runId: "1".repeat(32), runKind: "deploy", designRunId: design.runId, status: "FAILED", createdAt: 20 });
    const fresh = r({ runId: "2".repeat(32), runKind: "deploy", designRunId: design.runId, status: "RUNNING", awaitingHitl: true, createdAt: 30 });
    const ps = groupProjects([old, fresh, design]);
    expect(ps).toHaveLength(1);
    expect(ps[0]).toMatchObject({ id: design.runId, stage: { id: "needs_you" } });
    expect(ps[0]!.deploy!.runId).toBe(fresh.runId);
  });
  it("keeps a deploy run whose design run is not listed as its own project, newest first", () => {
    const loose = r({ runId: "3".repeat(32), runKind: "deploy", designRunId: "gone", createdAt: 50 });
    expect(groupProjects([design, loose]).map((p) => p.id)).toEqual([loose.runId, design.runId]);
  });
  it("names the stage of every state", () => {
    const d = (status: string) => r({ status });
    const dep = (status: string, awaitingHitl = false) => r({ runKind: "deploy", status, awaitingHitl });
    expect(stageOf(d("RUNNING"), null).id).toBe("analyzing");
    expect(stageOf(d("AWAITING_INPUT"), null).id).toBe("analyzing");
    expect(stageOf(d("FAILED"), null).id).toBe("design_failed");
    expect(stageOf(d("DELIVERED"), null).id).toBe("review");
    expect(stageOf(d("DELIVERED"), dep("RUNNING")).id).toBe("deploying");
    expect(stageOf(d("DELIVERED"), dep("RUNNING", true)).id).toBe("needs_you");
    expect(stageOf(d("DELIVERED"), dep("FAILED")).id).toBe("deploy_stopped");
    expect(stageOf(d("DELIVERED"), dep("DELIVERED")).id).toBe("complete");
    expect(() => stageOf(null, null)).toThrow("needs a design run");
  });
  it("filters and counts", () => {
    const ps = groupProjects([design, r({ runId: "e".repeat(32), customerId: "zeta", status: "FAILED", createdAt: 5 })]);
    expect(countProjects(ps)).toEqual({ all: 2, attention: 0, active: 0, complete: 0, failed: 1 });
    expect(filterProjects(ps, { status: "failed", query: "" })).toHaveLength(1);
    expect(filterProjects(ps, { status: "all", query: "ZET" })).toHaveLength(1);
    expect(filterProjects(ps, { status: "all", query: "dddd" })).toHaveLength(1);
  });
});
describe("journey", () => {
  const base = { designStatus: "DELIVERED", hasPolicies: true, deployStatus: null };
  it("lists the policies step only when there are policies", () => {
    expect(journey(base, "review").map((s) => s.id)).toEqual(["analyze", "review", "policies", "deploy", "done"]);
    expect(journey({ ...base, hasPolicies: false }, "review").map((s) => s.id)).toEqual(["analyze", "review", "deploy", "done"]);
  });
  it("opens a step only when the one before it is finished", () => {
    const open = (i: Parameters<typeof journey>[0]) => journey(i, "analyze").filter((s) => s.open).map((s) => s.id);
    expect(open({ ...base, designStatus: "RUNNING" })).toEqual(["analyze"]);
    expect(open(base)).toEqual(["analyze", "review", "policies", "deploy"]);
    expect(open({ ...base, deployStatus: "DELIVERED" })).toContain("done");
  });
  it("starts where the project is", () => {
    expect(startStep({ ...base, designStatus: "RUNNING" })).toBe("analyze");
    expect(startStep(base)).toBe("review");
    expect(startStep({ ...base, deployStatus: "RUNNING" })).toBe("deploy");
    expect(startStep({ ...base, deployStatus: "FAILED" })).toBe("deploy");
    expect(startStep({ ...base, deployStatus: "DELIVERED" })).toBe("done");
  });
  it("ignores a step in the address that is not open or does not exist", () => {
    expect(stepOrDefault("deploy", { ...base, designStatus: "RUNNING" })).toBe("analyze");
    expect(stepOrDefault("policies", { ...base, hasPolicies: false })).toBe("review");
    expect(stepOrDefault("policies", base)).toBe("policies");
    expect(stepOrDefault("nope", base)).toBe("review");
    expect(stepOrDefault(null, base)).toBe("review");
  });
  it("marks the current and finished steps", () => {
    const s = journey(base, "deploy");
    expect(s.find((x) => x.id === "deploy")!.state).toBe("current");
    expect(s.find((x) => x.id === "review")!.state).toBe("done");
    expect(s.find((x) => x.id === "done")!.state).toBe("todo");
  });
});
const scp = (): CustomScp => ({
  id: "protect-kms", title: "Protect KMS", targets: ["Workloads"], warnings: [],
  inputs: [{ name: "ADMIN_ROLE_NAME", description: "Role" }],
  policy: { Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: ["kms:ScheduleKeyDeletion"], Resource: "*",
    Condition: { ArnNotLike: { "aws:PrincipalArn": ["arn:aws:iam::*:role/{{ADMIN_ROLE_NAME}}"] } } }] },
});
describe("scp drafts", () => {
  it("finds the placeholders and the values still missing", () => {
    const d = draftOf(scp());
    expect(placeholders(d.policyText)).toEqual(["ADMIN_ROLE_NAME"]);
    expect(missingValues(d)).toEqual(["ADMIN_ROLE_NAME"]);
    expect(missingValues({ ...d, values: { ADMIN_ROLE_NAME: "  " } })).toEqual(["ADMIN_ROLE_NAME"]);
    expect(missingValues({ ...d, values: { ADMIN_ROLE_NAME: "Admin" } })).toEqual([]);
  });
  it("fills values into strings and keys, never the structure", () => {
    const out = fillPolicy({ "a/{{X}}": ["{{X}} and {{Y}}", 1] }, { X: 'v"], "Effect": "Allow' });
    expect(out).toEqual({ 'a/v"], "Effect": "Allow': ['v"], "Effect": "Allow and {{Y}}', 1] });
  });
  it("is dirty only when the policy or a value changed", () => {
    const e = scp(), d = draftOf(e);
    expect(isDirty(e, d)).toBe(false);
    expect(isDirty(e, { ...d, values: { ADMIN_ROLE_NAME: "Admin" } })).toBe(true);
    expect(isDirty(e, { ...d, policyText: d.policyText + " " })).toBe(true);
    const saved = { ...e, inputs: [{ ...e.inputs[0]!, value: "Admin" }] };
    expect(isDirty(saved, draftOf(saved))).toBe(false);
  });
  it("sends the policy only when its text changed, and a value for each placeholder it uses", () => {
    const e = scp(), d = draftOf(e);
    expect(buildEdits([e], { [e.id]: d })).toEqual([]);
    expect(buildEdits([e], { [e.id]: { ...d, values: { ADMIN_ROLE_NAME: " Admin " } } })).toEqual([{ id: e.id, values: { ADMIN_ROLE_NAME: "Admin" } }]);
    const edited = d.policyText.replace("{{ADMIN_ROLE_NAME}}", "{{OTHER}}");
    const [edit] = buildEdits([e], { [e.id]: { policyText: edited, values: { ADMIN_ROLE_NAME: "stale", OTHER: "x" } } });
    expect(Object.keys(edit!.values!)).toEqual(["OTHER"]);  // the value of a removed placeholder is not sent
    expect(edit!.policy).toBeDefined();
    expect(() => buildEdits([e], { [e.id]: { policyText: "{nope", values: {} } })).toThrow("not valid JSON");
  });
  it("refuses what the server refuses", () => {
    expect(valueError("X", "a{{b")).toMatch(/must not contain/);
    expect(valueError("X", "x".repeat(201))).toMatch(/longer than/);
    expect(valueError("X", "a\nb")).toMatch(/control/);
    expect(valueError("X", "role/Admin")).toBeNull();
    expect(parsePolicy("[]")).toEqual({ error: "The policy must be a JSON object." });
    expect(draftError({ policyText: "{", values: {} })).toMatch(/not valid JSON/);
    expect(draftError({ policyText: '{"a":"{{X}}"}', values: { X: "{{Y}}" } })).toMatch(/must not contain/);
    expect(draftError(draftOf(scp()))).toBeNull();
  });
});
