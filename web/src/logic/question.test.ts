import { describe, expect, it } from "vitest";
import { message, run, task } from "../test/fixtures";
import { answeredPending, canDecideHere, consoleLink, decidedPending, optionIndex, questionKey, suggestionAction, suggestionLabel } from "./question";

const noted = (type: "option" | "approval" | "text" | "steps" | undefined, suggestion: string, over = {}) =>
  message({ agentNote: { reason: "r", suggestion, suggestionType: type }, ...over });

describe("suggestionAction", () => {
  it("selects an offered option for option and approval suggestions, ignoring case", () => {
    expect(suggestionAction(noted("option", "landing zone"), true)).toEqual({ kind: "select", optionIndex: 0, approval: false });
    expect(suggestionAction(noted("approval", "End-to-End Migration"), true)).toEqual({ kind: "select", optionIndex: 1, approval: true });
  });
  it("does nothing when the suggested option is not on offer", () => {
    expect(suggestionAction(noted("option", "Deploy for me"), true)).toEqual({ kind: "none" });
  });
  it("offers a typed reply only for a message without options", () => {
    const free = { options: [], choices: [] };
    expect(suggestionAction(noted("text", "Use prefix x", free), true)).toEqual({ kind: "reply", text: "Use prefix x" });
    expect(suggestionAction(noted("text", "Use prefix x"), true)).toEqual({ kind: "none" });
  });
  it("never acts on steps, on an untyped suggestion, or for someone who cannot answer", () => {
    expect(suggestionAction(noted("steps", "Open the console"), true)).toEqual({ kind: "none" });
    expect(suggestionAction(noted(undefined, "Landing Zone"), true)).toEqual({ kind: "none" });
    expect(suggestionAction(noted("option", "Landing Zone"), false)).toEqual({ kind: "none" });
  });
  it("needs a message with an id", () => {
    expect(suggestionAction(noted("option", "Landing Zone", { messageId: null }), true)).toEqual({ kind: "none" });
  });
});

describe("helpers", () => {
  it("names the question by job and message or task", () => {
    expect(questionKey(message())).toBe("job-1:m-1");
    expect(questionKey(task())).toBe("job-1:t-1");
  });
  it("matches an option label exactly", () => {
    expect(optionIndex(message(), " LANDING ZONE ")).toBe(0);
    expect(optionIndex(message(), "Landing")).toBe(-1);
  });
  it("lets an approver decide only TOOL_APPROVAL tasks", () => {
    expect(canDecideHere(task(), true)).toBe(true);
    expect(canDecideHere(task(), false)).toBe(false);
    expect(canDecideHere(task({ category: "HITL" }), true)).toBe(false);
    expect(canDecideHere(task({ category: null }), true)).toBe(false);
    expect(canDecideHere(message(), true)).toBe(false);
  });
  it("matches a recorded answer or decision to the question on screen", () => {
    const p = message();
    expect(answeredPending(run(p, { pendingAnswer: { jobId: "job-1", messageId: "m-1", status: "sent", by: "u", at: 1 } }), p)).not.toBeNull();
    expect(answeredPending(run(p, { pendingAnswer: { jobId: "job-1", messageId: "other", status: "sent", by: "u", at: 1 } }), p)).toBeNull();
    const t = task();
    expect(decidedPending(run(t, { pendingDecision: { jobId: "job-1", taskId: "t-1", decision: "approve", by: "u", at: 1 } }), t)).not.toBeNull();
    expect(decidedPending(run(t), t)).toBeNull();
  });
  it("links only https AWS console URLs", () => {
    expect(consoleLink({ reason: "r", link: "https://ap-south-1.console.aws.amazon.com/transform/connector/c/configure" })).not.toBeNull();
    for (const bad of ["http://ap-south-1.console.aws.amazon.com/x", "https://evil.example.com/", "https://console.aws.amazon.com.evil.com/x", "javascript:alert(1)"]) {
      expect(consoleLink({ reason: "r", link: bad })).toBeNull();
    }
  });
  it("labels suggestions by type", () => {
    expect(suggestionLabel("approval")).toBe("Suggested approval");
    expect(suggestionLabel(undefined)).toBe("Suggestion");
  });
});
