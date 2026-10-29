import type { AuditItem, Run } from "../api/client";
import { detailOf } from "./activity";
import { isUpdateOnly } from "./question";

export interface Step {
  name: string;
  sub: string;
  state: "done" | "active" | "failed" | "";
  waiting: boolean;
}

const STEPS: [string, string][] = [
  ["Discover baseline", "Organizations snapshot and gap analysis"],
  ["Build with AWS Transform", "Transform plans and builds; the deploy agent answers from the design"],
  ["Assess and plan", "Foundation assessment and IaC change plan"],
  ["Attest and deliver", "Foundation report and artifacts"],
];

/** Where a deploy run is, from its audit log (the Progress card). */
export function deploySteps(run: Run, audit: AuditItem[]): Step[] {
  const p = run.pendingHumanInput;
  const waitingOnPerson = run.status === "RUNNING" && (run.awaitingHitl === true || (!!p && !isUpdateOnly(p)));
  const has = (action: string) => audit.some((x) => x.action === action);
  // Done when Transform reports the job finished, or when the platform closed it after verifying the account.
  const jobDone = audit.some((x) => (x.action === "tool.transform_poll_analyze_job" && detailOf(x).done === true) || x.action === "transform.job_closed");
  const done = [
    has("tool.run_pre_discover") || has("tool.run_pre_discover.failed"),
    jobDone,
    has("tool.save_iac_change_plan") || has("tool.render_iac_bundles"),
    has("deploy.attested") || (run.status === "DELIVERED" && has("phase.completed")),
  ];
  const next = done.indexOf(false);
  const failed = run.status === "FAILED";
  return STEPS.map(([name, sub], i) => {
    const state: Step["state"] = done[i] ? "done" : i === next ? (failed ? "failed" : run.status === "AWAITING_INPUT" ? "" : "active") : "";
    const waiting = state === "active" && waitingOnPerson;
    const text = done[i] ? "Done" : state === "failed" ? "Stopped here" : waiting ? "Waiting for your answer" : state === "active" ? "In progress" : sub;
    return { name, sub: text, state, waiting };
  });
}
const DESIGN_STEPS: [string, string][] = [
  ["Read the SOW", "Extract the text"],
  ["Understand the scope", "Map every requirement"],
  ["Generate the code", "Terraform and CloudFormation"],
  ["Validate and scan", "Lint and security scan"],
];
/** Where a design run is, from its audit log. */
export function designSteps(run: Run, audit: AuditItem[]): Step[] {
  const has = (a: string) => audit.some((x) => x.action === a);
  const done = [has("sow.extracted"), has("phase.completed"), has("bundle.rendered"), run.status === "DELIVERED"];
  const next = done.indexOf(false);
  const failed = run.status === "FAILED";
  return DESIGN_STEPS.map(([name, sub], i) => {
    const state: Step["state"] = done[i] ? "done" : i === next ? (failed ? "failed" : run.status === "AWAITING_INPUT" ? "" : "active") : "";
    return { name, sub: done[i] ? "Done" : state === "failed" ? "Stopped here" : state === "active" ? "In progress" : sub, state, waiting: false };
  });
}
