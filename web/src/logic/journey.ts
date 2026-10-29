/** The steps of a project, in the order a person does them. A step is open once the one before it has what it needs. */
export type StepId = "analyze" | "review" | "policies" | "deploy" | "done";
export interface JourneyInput {
  designStatus: string;
  /** The design has custom SCPs to review. */
  hasPolicies: boolean;
  deployStatus: string | null;
}
export interface JourneyStep { id: StepId; label: string; state: "done" | "current" | "todo"; open: boolean }
const LABELS: Record<StepId, string> = { analyze: "Analyze SOW", review: "Review design", policies: "Edit policies", deploy: "Deploy", done: "Results" };
export function journey(i: JourneyInput, current: StepId): JourneyStep[] {
  const delivered = i.designStatus === "DELIVERED";
  const deployed = i.deployStatus === "DELIVERED";
  const ids: StepId[] = ["analyze", "review", ...(i.hasPolicies ? (["policies"] as const) : []), "deploy", "done"];
  const open: Record<StepId, boolean> = { analyze: true, review: delivered, policies: delivered, deploy: delivered, done: deployed };
  const done: Record<StepId, boolean> = { analyze: delivered, review: delivered && (current !== "analyze" && current !== "review"), policies: delivered && (current === "deploy" || current === "done"),
    deploy: deployed, done: deployed };
  return ids.map((id) => ({ id, label: LABELS[id], open: open[id], state: id === current ? "current" : done[id] ? "done" : "todo" }));
}
/** Where a person should land when they open a project. */
export function startStep(i: JourneyInput): StepId {
  if (i.designStatus !== "DELIVERED") return "analyze";
  if (i.deployStatus === "DELIVERED") return "done";
  if (i.deployStatus) return "deploy";
  return "review";
}
export const stepOrDefault = (wanted: string | null, i: JourneyInput): StepId => {
  const steps = journey(i, startStep(i));
  const hit = steps.find((s) => s.id === wanted && s.open);
  return hit ? hit.id : startStep(i);
};
