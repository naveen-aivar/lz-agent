import type { RunSummary } from "../api/client";
import { isDone, pretty } from "./format";

export type StatusFilter = "all" | "attention" | "active" | "failed" | "delivered";
export type KindFilter = "all" | "design" | "deploy";

export interface RunFilter { status: StatusFilter; kind: KindFilter; query: string }

/** A deploy run that is waiting for a person (an answer or an approval). */
export const needsAttention = (r: RunSummary): boolean => r.status === "RUNNING" && r.awaitingHitl === true;

export function filterRuns(runs: RunSummary[], f: RunFilter): RunSummary[] {
  const q = f.query.trim().toLowerCase();
  return runs.filter((r) => {
    if (f.kind === "design" && r.runKind === "deploy") return false;
    if (f.kind === "deploy" && r.runKind !== "deploy") return false;
    if (f.status === "attention" && !needsAttention(r)) return false;
    if (f.status === "active" && isDone(r.status)) return false;
    if (f.status === "failed" && r.status !== "FAILED") return false;
    if (f.status === "delivered" && r.status !== "DELIVERED") return false;
    return !q || pretty(r.customerId).toLowerCase().includes(q) || (r.customerId ?? "").toLowerCase().includes(q) || r.runId.startsWith(q);
  });
}

export function countByStatus(runs: RunSummary[]): Record<StatusFilter, number> {
  return {
    all: runs.length,
    attention: runs.filter(needsAttention).length,
    active: runs.filter((r) => !isDone(r.status)).length,
    failed: runs.filter((r) => r.status === "FAILED").length,
    delivered: runs.filter((r) => r.status === "DELIVERED").length,
  };
}

/** "Moon Trades" -> "moon-trades": the run name the API accepts (3-40 of a-z, 0-9, -). */
export const slug = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
