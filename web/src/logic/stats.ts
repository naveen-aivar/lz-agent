import type { RunSummary } from "../api/client";
import { isDone } from "./format";

export interface Stats {
  total: number;
  delivered: number;
  failed: number;
  inProgress: number;
  /** Percent of finished runs that were delivered, or null when none has finished. */
  successRate: number | null;
}

/** Counts over the runs started in the last 30 days (the list holds the 25 newest). */
export function runStats(runs: RunSummary[], nowMs: number = Date.now()): Stats {
  const recent = runs.filter((r) => nowMs / 1000 - r.createdAt < 30 * 86400);
  const delivered = recent.filter((r) => r.status === "DELIVERED").length;
  const failed = recent.filter((r) => r.status === "FAILED").length;
  return {
    total: recent.length,
    delivered,
    failed,
    inProgress: recent.filter((r) => !isDone(r.status)).length,
    successRate: delivered + failed ? (delivered / (delivered + failed)) * 100 : null,
  };
}
