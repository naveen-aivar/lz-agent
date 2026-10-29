import { describe, expect, it } from "vitest";
import type { AuditItem, Run } from "../api/client";
import { allActivity, feedText, latestActivity } from "./activity";
import { deploySteps } from "./steps";
import { runStats } from "./stats";

const row = (action: string, ts: number, detail: object = {}, actor = "system"): AuditItem =>
  ({ SK: `AUDIT#${ts}#x`, action, actor, ts, detail: JSON.stringify(detail) });
const run = (over: Partial<Run> = {}): Run => ({ runId: "r", status: "RUNNING", ...over });

describe("feedText", () => {
  it("says who answered", () => {
    expect(feedText(row("transform.answer_sent", 1, { option: "Landing Zone" }, "agent"), "me")).toBe("Deploy agent answered “Landing Zone”");
    expect(feedText(row("transform.answer_sent", 1, { option: "Approve" }, "me"), "me")).toBe("You answered “Approve”");
    expect(feedText(row("transform.answer_sent", 1, { text: "x" }, "someone"), "me")).toBe("A user answered with a message");
  });
  it("words escalations, questions and failures", () => {
    expect(feedText(row("transform.agent_escalated", 1, { title: "Skip SCPs?" }), "me")).toBe("Deploy agent handed you: Skip SCPs?");
    expect(feedText(row("phase.awaiting_human", 1, { title: "Q" }), "me")).toBe("Transform asked: Q");
    expect(feedText(row("tool.render_iac_bundles.failed", 1, { error: "boom" }), "me")).toContain("boom");
  });
  it("falls back to the raw action name for an event it has no wording for", () => {
    expect(feedText(row("something.new", 1), "me")).toBe("something.new");
  });
});

describe("activity lists", () => {
  const audit = [row("deploy.sequencer.step", 1), row("run.started", 2), row("phase.continue", 3), row("deploy.started", 4)];
  it("hides routine events and shows newest first", () => {
    expect(latestActivity(audit).map((a) => a.action)).toEqual(["deploy.started", "run.started"]);
    expect(allActivity(audit, false).map((a) => a.ts)).toEqual([4, 2]);
    expect(allActivity(audit, true).map((a) => a.ts)).toEqual([4, 3, 2, 1]);
  });
  it("keeps only the newest seven", () => {
    const many = Array.from({ length: 12 }, (_, i) => row("run.created", i + 1));
    expect(latestActivity(many).map((a) => a.ts)).toEqual([12, 11, 10, 9, 8, 7, 6]);
  });
});

describe("deploySteps", () => {
  it("marks completed steps and the active one", () => {
    const steps = deploySteps(run(), [row("tool.run_pre_discover", 1), row("tool.transform_poll_analyze_job", 2, { done: true })]);
    expect(steps.map((s) => s.state)).toEqual(["done", "done", "active", ""]);
    expect(steps[2]!.sub).toBe("In progress");
  });
  it("says when the run waits for a person", () => {
    const steps = deploySteps(run({ awaitingHitl: true }), [row("tool.run_pre_discover", 1)]);
    expect(steps[1]).toMatchObject({ state: "active", waiting: true, sub: "Waiting for your answer" });
  });
  it("does not call a progress-only update a wait", () => {
    const pending = { source: "transform", jobId: "j", kind: "message", title: "t", text: "t", options: [], consoleUrl: "https://x", agentNote: { reason: "r", informational: true } } as Run["pendingHumanInput"];
    expect(deploySteps(run({ pendingHumanInput: pending }), [row("tool.run_pre_discover", 1)])[1]!.waiting).toBe(false);
  });
  it("shows where a failed run stopped", () => {
    const steps = deploySteps(run({ status: "FAILED" }), [row("tool.run_pre_discover", 1)]);
    expect(steps[1]).toMatchObject({ state: "failed", sub: "Stopped here" });
  });
  it("completes every step for a delivered run", () => {
    const steps = deploySteps(run({ status: "DELIVERED" }), [row("tool.run_pre_discover", 1), row("tool.transform_poll_analyze_job", 2, { done: true }),
      row("tool.save_iac_change_plan", 3), row("phase.completed", 4)]);
    expect(steps.every((s) => s.state === "done")).toBe(true);
  });
});

describe("runStats", () => {
  const now = 1_000_000_000_000;
  const r = (status: string, ageDays: number) => ({ runId: status + ageDays, status, createdAt: now / 1000 - ageDays * 86400, error: "" });
  it("counts the last 30 days and the success rate of finished runs", () => {
    const s = runStats([r("DELIVERED", 1), r("FAILED", 2), r("RUNNING", 0), r("DELIVERED", 40)], now);
    expect(s).toEqual({ total: 3, delivered: 1, failed: 1, inProgress: 1, successRate: 50 });
  });
  it("has no success rate before a run finishes", () => {
    expect(runStats([r("RUNNING", 0)], now).successRate).toBeNull();
    expect(runStats([], now).successRate).toBeNull();
  });
});
