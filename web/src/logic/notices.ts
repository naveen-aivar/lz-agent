import type { AuditItem, Run } from "../api/client";
import { detailOf } from "./activity";
export interface Notice { tone: "warn" | "info"; title: string; body: string; hint?: string }
const ROUTINE = /^transform_analyze_waiting$|already polled this invoke$|^deploy_judgment complete/;
const PLATFORM = /permission|IAM|AccessDenied|not authorized|s3:|organization|create-organization|platform account|run_pre_discover|NotInUse/i;
const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n)}…` : s);
const last = (audit: AuditItem[], action: string): AuditItem | undefined => [...audit].reverse().find((a) => a.action === action);
/** Why a deploy run is paused, from the platform's own audit events (display only). Routine Transform waits give no notice. */
export function pauseNotice(audit: AuditItem[], run: Run): Notice | null {
  const cont = last(audit, "phase.continue");
  const yielded = last(audit, "tool.yield_for_orchestrator");
  const d = cont ? detailOf(cont) : {};
  const reason = String(d.reason || (yielded ? detailOf(yielded).reason : "") || "").trim();
  if (!cont && !reason) return null;
  if (ROUTINE.test(reason)) return null;
  const acct = run.deployTarget && (run.deployTarget as { accountId?: string }).accountId;
  if (/^Pre-discover failed for deploy target account/i.test(reason)) {
    return { tone: "warn", title: "Deploy paused (target discover).", body: clip(reason, 480),
      hint: `Fix the issue in ${acct ? `account ${acct}` : "the target account"}, then resume or start a new deploy run.` };
  }
  const platform = PLATFORM.test(reason);
  if (d.awaitingHitl && !platform) {
    return { tone: "info", title: "Waiting on AWS Transform.", body: "Complete the required step in the Transform workspace. The deploy agent resumes on its own." };
  }
  if (!reason) return null;
  return { tone: platform ? "warn" : "info", title: platform ? "Deploy paused (platform setup)." : "Deploy paused.", body: clip(reason, 420),
    hint: "Step Functions retries until you stop the run or it fails." };
}
