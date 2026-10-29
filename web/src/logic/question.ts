import type { AgentNote, PendingAnswer, PendingDecision, PendingHumanInput, Run } from "../api/client";

export const questionKey = (p: PendingHumanInput): string => `${p.jobId}:${p.messageId ?? p.taskId ?? p.title}`;

export const isUpdateOnly = (p: PendingHumanInput): boolean => p.agentNote?.informational === true;

const norm = (s: string): string => s.trim().toLowerCase();

/** Index of the offered option whose label the suggestion names exactly (ignoring case and outer spaces), or -1. */
export const optionIndex = (p: PendingHumanInput, suggestion: string): number =>
  p.options.findIndex((o) => norm(o) === norm(suggestion));

export type SuggestionAction =
  | { kind: "none" }
  | { kind: "select"; optionIndex: number; approval: boolean }
  | { kind: "reply"; text: string };

/**
 * What the suggestion button does. The agent types its suggestion: "option" and "approval" name an offered option
 * (selected for the person, who still confirms), "text" is a typed reply (put in the box for the person to edit and
 * send), "steps" has no button. A suggestion without a type gets no button: it is shown, never acted on.
 */
export function suggestionAction(p: PendingHumanInput, canAnswer: boolean): SuggestionAction {
  const note: AgentNote | undefined = p.agentNote;
  if (!note?.suggestion || !canAnswer || p.kind !== "message" || !p.messageId) return { kind: "none" };
  switch (note.suggestionType) {
    case "option":
    case "approval": {
      const i = optionIndex(p, note.suggestion);
      return i < 0 ? { kind: "none" } : { kind: "select", optionIndex: i, approval: note.suggestionType === "approval" };
    }
    case "text":
      return p.options.length ? { kind: "none" } : { kind: "reply", text: note.suggestion };
    default:
      return { kind: "none" };
  }
}

/** A task a signed-in approver can approve or reject here (the platform submits it to Transform). */
export const canDecideHere = (p: PendingHumanInput, canAnswer: boolean): boolean =>
  canAnswer && p.kind === "task" && p.category === "TOOL_APPROVAL" && !!p.taskId;

export const answeredPending = (run: Run, p: PendingHumanInput): PendingAnswer | null =>
  run.pendingAnswer && p.messageId && run.pendingAnswer.messageId === p.messageId ? run.pendingAnswer : null;

export const decidedPending = (run: Run, p: PendingHumanInput): PendingDecision | null =>
  run.pendingDecision && p.taskId && run.pendingDecision.taskId === p.taskId ? run.pendingDecision : null;

const CONSOLE_LINK = /^https:\/\/[a-z0-9-]+\.console\.aws\.amazon\.com\//;

/** Only AWS console links from the agent are rendered as links. */
export const consoleLink = (note: AgentNote | undefined): string | null =>
  note?.link && CONSOLE_LINK.test(note.link) ? note.link : null;

const LABELS = { option: "Suggested option", approval: "Suggested approval", text: "Suggested reply", steps: "Suggested steps" } as const;
export const suggestionLabel = (type: AgentNote["suggestionType"]): string => (type ? LABELS[type] : "Suggestion");

export const ANSWER_LIMIT = 4000;
