import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { message, run, task } from "../test/fixtures";
import { QuestionPanel } from "./QuestionPanel";

const api = () => ({
  answerQuestion: vi.fn().mockResolvedValue({ pendingAnswer: {} }),
  decideTask: vi.fn().mockResolvedValue({ pendingDecision: {} }),
});
const setup = (pending = message(), over: { canAnswer?: boolean; run?: ReturnType<typeof run> } = {}) => {
  const a = api();
  const onChanged = vi.fn();
  render(<QuestionPanel run={over.run ?? run(pending)} pending={pending} canAnswer={over.canAnswer ?? true} userSub="me" api={a} onChanged={onChanged} />);
  return { a, onChanged, user: userEvent.setup() };
};

describe("QuestionPanel messages", () => {
  it("selects an option, confirms it and sends it", async () => {
    const { a, onChanged, user } = setup();
    await user.click(screen.getByRole("button", { name: "Landing Zone" }));
    expect(screen.getByRole("group", { name: "Confirm answer" })).toHaveTextContent("Send “Landing Zone” to AWS Transform?");
    expect(a.answerQuestion).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Send answer" }));
    await waitFor(() => expect(a.answerQuestion).toHaveBeenCalledWith(run().runId, { jobId: "job-1", messageId: "m-1", option: "Landing Zone" }));
    expect(onChanged).toHaveBeenCalled();
  });

  it("sends a typed reply trimmed", async () => {
    const { a, user } = setup(message({ options: [], choices: [] }));
    await user.type(screen.getByLabelText("Your reply to Transform"), "  Use prefix x  ");
    await user.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(a.answerQuestion).toHaveBeenCalledWith(run().runId, { jobId: "job-1", messageId: "m-1", text: "Use prefix x" }));
  });

  it("selects the suggested option for the person without sending it", async () => {
    const { a, user } = setup(message({ agentNote: { reason: "Run purpose.", suggestion: "Landing Zone", suggestionType: "option" } }));
    expect(screen.getByTestId("suggestion")).toHaveTextContent("Suggested option: Landing Zone");
    await user.click(screen.getByRole("button", { name: "Select this option" }));
    expect(screen.getByRole("group", { name: "Confirm answer" })).toBeInTheDocument();
    expect(a.answerQuestion).not.toHaveBeenCalled();
  });

  it("marks an approval suggestion and still waits for the person to confirm", async () => {
    const { a, user } = setup(message({ options: ["Proceed", "Modify plan"], choices: [], agentNote: { reason: "Starts provisioning.", suggestion: "Proceed", suggestionType: "approval" } }));
    await user.click(screen.getByRole("button", { name: "Select this option to approve" }));
    expect(screen.getByText(/approves or starts something in AWS/)).toBeInTheDocument();
    expect(a.answerQuestion).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Send answer" }));
    await waitFor(() => expect(a.answerQuestion).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ option: "Proceed" })));
  });

  it("puts a typed suggestion in the reply box for editing", async () => {
    const { a, user } = setup(message({ options: [], choices: [], agentNote: { reason: "Email convention.", suggestion: "Prefix billu.naveen, domain aivar.tech.", suggestionType: "text" } }));
    await user.click(screen.getByRole("button", { name: "Use this as my reply" }));
    expect(screen.getByLabelText("Your reply to Transform")).toHaveValue("Prefix billu.naveen, domain aivar.tech.");
    expect(a.answerQuestion).not.toHaveBeenCalled();
  });

  it("shows steps without a button and an AWS console link only for real console URLs", () => {
    setup(task({ category: "HITL", agentNote: { reason: "Do it in the console.", suggestion: "Connect account 1.", suggestionType: "steps", link: "https://ap-south-1.console.aws.amazon.com/transform/connector/c/configure" } }));
    expect(screen.getByTestId("suggestion")).toHaveTextContent("Suggested steps: Connect account 1.");
    expect(screen.queryByRole("button", { name: /Select|Use this/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Approve in the AWS console/ })).toHaveAttribute("href", expect.stringContaining("console.aws.amazon.com"));
  });

  it("does not render a link the agent supplied for a non-console URL", () => {
    setup(task({ category: "HITL", agentNote: { reason: "x", link: "https://evil.example.com/transform" } }));
    expect(screen.queryByRole("link", { name: /Approve in the AWS console/ })).toBeNull();
  });

  it("renders Markdown in the question but never raw HTML or non-https links", () => {
    setup(message({ text: "<img src=x onerror=alert(1)> **bold**\n\n[ok](https://example.com) [bad](javascript:alert(1))" }));
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByRole("link", { name: "ok" })).toHaveAttribute("href", "https://example.com");
    expect(screen.queryByRole("link", { name: "bad" })).toBeNull();
  });

  it("explains that only approvers can answer, and offers no way to send", () => {
    setup(message(), { canAnswer: false });
    expect(screen.getByText(/Only members of the approver group/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Landing Zone" })).toBeNull();
  });

  it("shows what was sent instead of the controls", () => {
    const p = message();
    setup(p, { run: run(p, { pendingAnswer: { jobId: "job-1", messageId: "m-1", option: "Landing Zone", status: "sent", by: "agent", at: 1_793_248_712 } }) });
    expect(screen.getByRole("status")).toHaveTextContent("Sent “Landing Zone” to AWS Transform (by the deploy agent)");
    expect(screen.queryByRole("button", { name: "Send answer" })).toBeNull();
  });

  it("shows a failed send and keeps the controls", async () => {
    const { a, user } = setup();
    a.answerQuestion.mockRejectedValueOnce(new Error("AWS Transform has moved on"));
    await user.click(screen.getByRole("button", { name: "Landing Zone" }));
    await user.click(screen.getByRole("button", { name: "Send answer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("AWS Transform has moved on");
    expect(screen.getByRole("button", { name: "Send answer" })).toBeEnabled();
  });

  it("labels an update the agent judged to need no reply", () => {
    setup(message({ options: [], choices: [], agentNote: { reason: "Progress only.", informational: true } }));
    expect(screen.getByRole("heading", { name: "Update from AWS Transform" })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Deploy agent (no reply needed):");
  });
});

describe("QuestionPanel approval tasks", () => {
  it("asks for confirmation, then approves under the person's name", async () => {
    const { a, onChanged, user } = setup(task());
    await user.click(screen.getByRole("button", { name: "Approve in this app" }));
    expect(a.decideTask).not.toHaveBeenCalled();
    expect(screen.getByRole("group", { name: "Confirm decision" })).toHaveTextContent("Approve “Approve Landing Zone Deployment” in AWS Transform?");
    await user.click(screen.getByRole("button", { name: "Yes, approve" }));
    await waitFor(() => expect(a.decideTask).toHaveBeenCalledWith(run().runId, { jobId: "job-1", taskId: "t-1", decision: "approve" }));
    expect(onChanged).toHaveBeenCalled();
  });

  it("can be cancelled and can reject", async () => {
    const { a, user } = setup(task());
    await user.click(screen.getByRole("button", { name: "Approve in this app" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Approve in this app" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.click(screen.getByRole("button", { name: "Yes, reject" }));
    await waitFor(() => expect(a.decideTask).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ decision: "reject" })));
  });

  it("offers no approve button for a task with its own form or to a non-approver", () => {
    setup(task({ category: "HITL" }));
    expect(screen.queryByRole("button", { name: "Approve in this app" })).toBeNull();
    expect(screen.getByText(/its own form/)).toBeInTheDocument();
  });

  it("offers no approve button to someone outside the approver group", () => {
    setup(task(), { canAnswer: false });
    expect(screen.queryByRole("button", { name: "Approve in this app" })).toBeNull();
  });

  it("shows the recorded decision instead of the buttons", () => {
    const t = task();
    setup(t, { run: run(t, { pendingDecision: { jobId: "job-1", taskId: "t-1", decision: "approve", by: "me", at: 1_793_250_000 } }) });
    expect(screen.getByRole("status")).toHaveTextContent("Approved “Approve Landing Zone Deployment” in AWS Transform");
    expect(screen.queryByRole("button", { name: "Approve in this app" })).toBeNull();
  });
});
