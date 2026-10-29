export type Tone = "green" | "amber" | "red" | "blue" | "violet" | "muted";

export const pretty = (id?: string | null): string =>
  String(id ?? "").split("-").filter(Boolean).map((w) => w[0]!.toUpperCase() + w.slice(1)).join(" ");

export function ago(ts: number, nowMs: number = Date.now()): string {
  const s = Math.max(0, nowMs / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const when = (ts: number): string => new Date(ts * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

const STATE: Record<string, [Tone, string]> = {
  DELIVERED: ["green", "Ready to download"],
  FAILED: ["red", "Failed"],
  RUNNING: ["amber", "In progress"],
  AWAITING_INPUT: ["blue", "Starting"],
};

/** Badge tone and label for a run status. An unknown status is shown as is, in a neutral tone, never as success. */
export const stateOf = (status: string): [Tone, string] => STATE[status] ?? ["muted", status];

export const isDone = (status: string): boolean => status === "DELIVERED" || status === "FAILED";
