import type { RunSummary } from "../api/client";
import { isDone, pretty } from "./format";
import type { Tone } from "./format";
/** One customer's work: the design run and the newest deploy run built from it. Runs are grouped so a person sees one row. */
export interface Project {
  /** The design run id, or the deploy run id for a deploy run with no design run. */
  id: string;
  name: string;
  createdAt: number;
  design: RunSummary | null;
  deploy: RunSummary | null;
  stage: Stage;
}
export type StageId = "analyzing" | "design_failed" | "review" | "deploying" | "needs_you" | "deploy_stopped" | "complete";
export interface Stage { id: StageId; label: string; tone: Tone; next: string }
const STAGES: Record<StageId, Omit<Stage, "id">> = {
  analyzing: { label: "Analyzing the SOW", tone: "amber", next: "Open" },
  design_failed: { label: "Analysis failed", tone: "red", next: "See why" },
  review: { label: "Ready to review", tone: "blue", next: "Review" },
  deploying: { label: "Deploying", tone: "amber", next: "Open" },
  needs_you: { label: "Needs your answer", tone: "amber", next: "Answer" },
  deploy_stopped: { label: "Deploy stopped", tone: "red", next: "Resume" },
  complete: { label: "Complete", tone: "green", next: "View" },
};
const stage = (id: StageId): Stage => ({ id, ...STAGES[id] });
export function stageOf(design: RunSummary | null, deploy: RunSummary | null): Stage {
  if (deploy) {
    if (deploy.status === "DELIVERED") return stage("complete");
    if (deploy.status === "FAILED") return stage("deploy_stopped");
    return stage(deploy.awaitingHitl ? "needs_you" : "deploying");
  }
  if (!design) throw new Error("a project needs a design run or a deploy run");
  if (design.status === "DELIVERED") return stage("review");
  if (design.status === "FAILED") return stage("design_failed");
  return stage("analyzing");
}
/** Groups runs into projects, newest first. A deploy run whose design run is not in the list gets a row of its own. */
export function groupProjects(runs: RunSummary[]): Project[] {
  const byId = new Map(runs.map((r) => [r.runId, r]));
  const deploys = new Map<string, RunSummary>();
  const loose: RunSummary[] = [];
  for (const r of runs) {
    if (r.runKind !== "deploy") continue;
    if (r.designRunId && byId.has(r.designRunId)) {
      const cur = deploys.get(r.designRunId);
      if (!cur || r.createdAt > cur.createdAt) deploys.set(r.designRunId, r);
    } else loose.push(r);
  }
  const make = (design: RunSummary | null, deploy: RunSummary | null): Project => {
    const first = (design ?? deploy)!;
    return { id: first.runId, name: pretty(first.customerId) || first.runId.slice(0, 8), createdAt: first.createdAt, design, deploy, stage: stageOf(design, deploy) };
  };
  const projects = [
    ...runs.filter((r) => r.runKind !== "deploy").map((d) => make(d, deploys.get(d.runId) ?? null)),
    ...loose.map((d) => make(null, d)),
  ];
  return projects.sort((a, b) => b.createdAt - a.createdAt);
}
export type ProjectFilter = "all" | "attention" | "active" | "complete" | "failed";
const isFailed = (p: Project): boolean => p.stage.id === "design_failed" || p.stage.id === "deploy_stopped";
export const needsYou = (p: Project): boolean => p.stage.id === "needs_you";
export const inProgress = (p: Project): boolean => !!(p.deploy ?? p.design) && !isDone((p.deploy ?? p.design)!.status);
export function filterProjects(ps: Project[], f: { status: ProjectFilter; query: string }): Project[] {
  const q = f.query.trim().toLowerCase();
  return ps.filter((p) => {
    if (f.status === "attention" && !needsYou(p)) return false;
    if (f.status === "active" && !inProgress(p)) return false;
    if (f.status === "complete" && p.stage.id !== "complete") return false;
    if (f.status === "failed" && !isFailed(p)) return false;
    return !q || p.name.toLowerCase().includes(q) || [p.design?.runId, p.deploy?.runId].some((id) => id?.startsWith(q));
  });
}
export const countProjects = (ps: Project[]): Record<ProjectFilter, number> => ({
  all: ps.length, attention: ps.filter(needsYou).length, active: ps.filter(inProgress).length,
  complete: ps.filter((p) => p.stage.id === "complete").length, failed: ps.filter(isFailed).length,
});
