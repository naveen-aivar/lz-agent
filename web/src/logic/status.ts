export type Tone = "green" | "amber" | "red" | "blue" | "muted";

/** Badge colour for a run status. An unknown status is shown neutral, never as success. */
export const statusTone = (status: string): Tone =>
  ({ DELIVERED: "green", RUNNING: "blue", AWAITING_INPUT: "amber", FAILED: "red" } as Record<string, Tone>)[status] ?? "muted";
