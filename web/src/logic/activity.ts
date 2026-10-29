import type { AuditItem } from "../api/client";
import { ACTIONS } from "./actions";

/** Routine events that would drown the feed: polling, reads and orchestration hops. */
export const FEED_SKIP = new Set([
  "deploy.sequencer.step", "phase.continue", "phase.started", "tool.transform_poll_analyze_job", "tool.read_deploy_checkpoint",
  "tool.read_deploy_context", "tool.read_approved_scope", "tool.yield_for_orchestrator",
]);

export function detailOf(a: AuditItem): Record<string, unknown> {
  try {
    const d = a.detail ? (JSON.parse(a.detail) as unknown) : {};
    return d && typeof d === "object" ? (d as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

const str = (v: unknown): string => (typeof v === "string" ? v : "");

/** One line for an event, as the classic UI words it. */
export function feedText(a: AuditItem, userSub: string): string {
  const d = detailOf(a);
  if (a.action === "transform.answer_sent") {
    const who = a.actor === "agent" ? "Deploy agent" : a.actor === userSub ? "You" : "A user";
    return `${who} answered ${str(d.option) ? `“${str(d.option)}”` : "with a message"}`;
  }
  if (a.action === "transform.agent_escalated") return `Deploy agent handed you: ${str(d.title) || "a Transform question"}`;
  if (a.action === "phase.awaiting_human" && str(d.title)) return `Transform asked: ${str(d.title)}`;
  if (a.action.endsWith(".failed") && str(d.error)) return `${ACTIONS[a.action] ?? a.action}: ${str(d.error).slice(0, 140)}`;
  return ACTIONS[a.action] ?? a.action;
}

/** The newest `n` events worth showing, newest first. */
export const latestActivity = (audit: AuditItem[], n = 7): AuditItem[] =>
  audit.filter((a) => !FEED_SKIP.has(a.action)).sort((a, b) => a.ts - b.ts).slice(-n).reverse();

export const allActivity = (audit: AuditItem[], showEverything: boolean): AuditItem[] =>
  [...audit].sort((a, b) => b.ts - a.ts).filter((a) => showEverything || !FEED_SKIP.has(a.action));
