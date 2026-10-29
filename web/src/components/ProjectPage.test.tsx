import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Client } from "../api/client";
import type { StepId } from "../logic/journey";
import { ToastProvider } from "../ui/Toasts";
import { ProjectPage } from "./ProjectPage";
import { SCOPE } from "../test/fixtures";
vi.mock("../ui/OrgDiagram", () => ({ OrgDiagram: () => <div>diagram</div> }));  // mermaid is heavy and has its own browser-only behavior
const DESIGN = "d".repeat(32);
const POLICY = {
  id: "protect-kms", title: "Protect KMS keys", description: "From section 4", targets: ["Workloads"], basis: "explicit", warnings: [],
  inputs: [{ name: "ADMIN_ROLE_NAME", description: "Role allowed to delete keys", example: "MT-Administrator" }],
  policy: { Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: ["kms:ScheduleKeyDeletion"], Resource: "*",
    Condition: { ArnNotLike: { "aws:PrincipalArn": ["arn:aws:iam::*:role/{{ADMIN_ROLE_NAME}}"] } } }] },
};
const scope = (customScps: unknown[] = [POLICY]) => ({ ...SCOPE, customScps, summary: { ...SCOPE.summary, customScps: customScps.length } });
function fake(over: Record<string, unknown> = {}, opts: { status?: string; deploys?: unknown[]; customScps?: unknown[] } = {}) {
  return {
    getRun: vi.fn().mockResolvedValue({ run: { runId: DESIGN, customerId: "acme", status: opts.status ?? "DELIVERED", createdAt: 1, artifacts: { terraform: {}, cloudformation: {}, reports: {} } } }),
    getAudit: vi.fn().mockResolvedValue({ audit: [] }),
    getScope: vi.fn().mockResolvedValue({ scope: scope(opts.customScps), sha: "sha-1", orgDiagram: "graph TD" }),
    listRuns: vi.fn().mockResolvedValue({ runs: opts.deploys ?? [], total: 0 }),
    getReportSummary: vi.fn(), getArtifact: vi.fn(),
    editCustomScps: vi.fn().mockImplementation(async (_id: string, body: { edits: { values: Record<string, string> }[] }) => ({
      scope: scope([{ ...POLICY, inputs: [{ ...POLICY.inputs[0], value: body.edits[0]!.values.ADMIN_ROLE_NAME }] }]), sha: "sha-2", orgDiagram: "graph TD" })),
    startDeploy: vi.fn().mockResolvedValue({ runId: "e".repeat(32) }), verifyDeployTarget: vi.fn(),
    ...over,
  } as unknown as Client & Record<string, ReturnType<typeof vi.fn>>;
}
function Host({ api, start = null }: { api: Client; start?: string | null }) {
  const [step, setStep] = useState<string | null>(start);
  return <ToastProvider><ProjectPage designId={DESIGN} api={api} canAnswer userSub="me" step={step} onStep={(s: StepId) => setStep(s)} pollMs={60000} /></ToastProvider>;
}
describe("ProjectPage", () => {
  it("starts a delivered design at the review step with the steps in order", async () => {
    render(<Host api={fake()} />);
    expect(await screen.findByText("Download the code")).toBeInTheDocument();
    const names = screen.getAllByRole("listitem").filter((li) => li.className.includes("stp")).map((li) => li.textContent);
    expect(names).toEqual(["✓Analyze SOW", "2Review design", "3Edit policies", "4Deploy", "5Results"]);
    expect(screen.getByRole("button", { name: /Next: Edit policies/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Results/ })).toBeDisabled();  // not reached yet
  });
  it("skips the policies step when the SOW needs no custom policy", async () => {
    render(<Host api={fake({}, { customScps: [] })} />);
    await screen.findByText("Download the code");
    expect(screen.queryByRole("button", { name: /Edit policies/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Next: Deploy/ })).toBeInTheDocument();
  });
  it("shows the analysis while it runs and keeps the later steps closed", async () => {
    const api = fake({ getScope: vi.fn().mockRejectedValue(new Error("not yet")) }, { status: "RUNNING" });
    render(<Host api={api} />);
    expect(await screen.findByText("The agent is reading the SOW")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Review design/ })).toBeDisabled();
  });
  it("lets a person fill the placeholders, save, and carry on to deploy", async () => {
    const user = userEvent.setup();
    const api = fake();
    render(<Host api={api} />);
    await user.click(await screen.findByRole("button", { name: /Next: Edit policies/ }));
    expect(await screen.findByText("Protect KMS keys")).toBeInTheDocument();
    expect(screen.getByText("1 value needed")).toBeInTheDocument();
    await user.type(screen.getByLabelText("ADMIN_ROLE_NAME"), "MT-Administrator");
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Next: Deploy/ })).toBeDisabled();  // save first
    await user.click(screen.getByRole("button", { name: "Save 1 change" }));
    await waitFor(() => expect(api.editCustomScps).toHaveBeenCalledWith(DESIGN, { baseSha: "sha-1", edits: [{ id: "protect-kms", values: { ADMIN_ROLE_NAME: "MT-Administrator" } }] }));
    expect(await screen.findByRole("button", { name: "No changes to save" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Next: Deploy/ }));
    expect(await screen.findByRole("heading", { name: "Where should the landing zone be built?" })).toBeInTheDocument();
  });
  it("shows the server's reason when a save is refused", async () => {
    const user = userEvent.setup();
    const api = fake({ editCustomScps: vi.fn().mockRejectedValue(new Error("the design changed since you opened it")) });
    render(<Host api={api} start="policies" />);
    await user.type(await screen.findByLabelText("ADMIN_ROLE_NAME"), "x");
    await user.click(screen.getByRole("button", { name: "Save 1 change" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("the design changed since you opened it");
  });
  it("refuses invalid policy JSON before sending", async () => {
    const user = userEvent.setup();
    const api = fake();
    render(<Host api={api} start="policies" />);
    await user.click(await screen.findByText("Edit the policy JSON"));
    const box = screen.getByLabelText("Policy JSON for Protect KMS keys");
    await user.clear(box);
    await user.type(box, "{{{{");
    expect(await screen.findAllByRole("alert")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: /Save|No changes/ })).toBeDisabled();
    expect(api.editCustomScps).not.toHaveBeenCalled();
  });
  it("starts the deploy from the same page and opens its progress there", async () => {
    const user = userEvent.setup();
    const api = fake();
    render(<Host api={api} start="deploy" />);
    await user.type(await screen.findByLabelText("AWS account ID"), "710507380209");
    await user.type(screen.getByLabelText("Role ARN"), "arn:aws:iam::710507380209:role/R");
    await user.type(screen.getByLabelText("External ID"), "ext");
    expect(screen.queryByLabelText(/Account email/)).not.toBeVisible();  // under Advanced
    await user.click(screen.getByRole("button", { name: "Start deploy" }));
    await waitFor(() => expect(api.startDeploy).toHaveBeenCalledWith(DESIGN, expect.objectContaining({ applyScps: true })));
    expect(((api.startDeploy as unknown as ReturnType<typeof vi.fn>).mock.calls[0]![1] as { deployTarget: { accountId: string } }).deployTarget.accountId).toBe("710507380209");
  });
  it("goes straight to the running deploy when there is one", async () => {
    const dep = { runId: "e".repeat(32), runKind: "deploy", designRunId: DESIGN, status: "RUNNING", createdAt: 5, customerId: "acme", error: "" };
    const api = fake({}, { deploys: [dep] });
    (api.getRun as unknown as ReturnType<typeof vi.fn>).mockImplementation(async (id: string) => ({
      run: id === DESIGN ? { runId: DESIGN, customerId: "acme", status: "DELIVERED", createdAt: 1, artifacts: {} }
        : { runId: id, runKind: "deploy", designRunId: DESIGN, customerId: "acme", status: "RUNNING", createdAt: 5 } }));
    render(<Host api={api} />);
    expect(await screen.findByText("Deploy run", { selector: "h1" })).toBeInTheDocument();
    expect(screen.getByText("Progress")).toBeInTheDocument();
    expect(screen.queryByText("← Runs")).toBeNull();
  });
});
