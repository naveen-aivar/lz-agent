import type { PendingHumanInput, Run } from "../api/client";

export const message = (over: Partial<PendingHumanInput> = {}): PendingHumanInput => ({
  source: "transform", jobId: "job-1", workspaceId: "ws-1", kind: "message", taskId: null, messageId: "m-1",
  title: "Transform is asking for a decision", text: "What would you like to accomplish today?",
  options: ["Landing Zone", "End-to-End Migration"], choices: [{ label: "Landing Zone", value: "Landing Zone" }, { label: "End-to-End Migration", value: "End-to-End Migration" }],
  consoleUrl: "https://transform.example.invalid/jobs/job-1", ...over,
});

export const task = (over: Partial<PendingHumanInput> = {}): PendingHumanInput => ({
  source: "transform", jobId: "job-1", workspaceId: "ws-1", kind: "task", taskId: "t-1", messageId: null,
  category: "TOOL_APPROVAL", title: "Approve Landing Zone Deployment", text: "Please review and approve.", options: [], choices: [],
  consoleUrl: "https://transform.example.invalid/jobs/job-1", ...over,
});

export const run = (pending?: PendingHumanInput, over: Partial<Run> = {}): Run => ({
  runId: "a".repeat(32), runKind: "deploy", status: "RUNNING", customerId: "acme", pendingHumanInput: pending, ...over,
});
