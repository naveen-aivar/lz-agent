import type { CustomScpEdit } from "../api/client";
import type { CustomScp } from "./design";
/** What a person is editing for one custom SCP. The policy stays a template: {{NAME}} marks a value still to enter. */
export interface Draft { policyText: string; values: Record<string, string> }
export const VALUE_MAX = 200;
const PLACEHOLDER = /\{\{([A-Z][A-Z0-9_]*)\}\}/g;
export const templateText = (e: CustomScp): string => JSON.stringify(e.policy, null, 2);
export const draftOf = (e: CustomScp): Draft => ({
  policyText: templateText(e),
  values: Object.fromEntries(e.inputs.filter((i) => i.value).map((i) => [i.name, i.value as string])),
});
/** The placeholders used in the text, sorted and without repeats. */
export const placeholders = (text: string): string[] => [...new Set([...text.matchAll(PLACEHOLDER)].map((m) => m[1]!))].sort();
/** The same rules as the server (lzcore.customscp.value_error), so the form can refuse before sending. */
export function valueError(name: string, value: string): string | null {
  if (value.length > VALUE_MAX) return `${name} is longer than ${VALUE_MAX} characters`;
  if (value.includes("{{") || value.includes("}}")) return `${name} must not contain {{ or }}`;
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f]/.test(value)) return `${name} must not contain control characters`;
  return null;
}
export function parsePolicy(text: string): { policy: Record<string, unknown> } | { error: string } {
  let v: unknown;
  try {
    v = JSON.parse(text);
  } catch (e) {
    return { error: `The policy is not valid JSON: ${e instanceof Error ? e.message : String(e)}` };
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) return { error: "The policy must be a JSON object." };
  return { policy: v as Record<string, unknown> };
}
/** The policy with every value that was entered put in place of its {{NAME}} (keys and strings, never the structure). */
export function fillPolicy(policy: unknown, values: Record<string, string>): unknown {
  const sub = (t: string): string => t.replace(PLACEHOLDER, (m, n: string) => (values[n] ? values[n] : m));
  const walk = (n: unknown): unknown =>
    Array.isArray(n) ? n.map(walk)
      : n && typeof n === "object" ? Object.fromEntries(Object.entries(n).map(([k, v]) => [sub(k), walk(v)]))
        : typeof n === "string" ? sub(n) : n;
  return walk(policy);
}
/** Inputs the policy text asks for that have no value yet. */
export const missingValues = (d: Draft): string[] => placeholders(d.policyText).filter((n) => !(d.values[n] ?? "").trim());
export const isDirty = (e: CustomScp, d: Draft): boolean => {
  const saved = draftOf(e);
  if (d.policyText !== saved.policyText) return true;
  return placeholders(d.policyText).some((n) => (d.values[n] ?? "").trim() !== (saved.values[n] ?? ""));
};
/** The first problem with a draft, or null. */
export function draftError(d: Draft): string | null {
  const parsed = parsePolicy(d.policyText);
  if ("error" in parsed) return parsed.error;
  for (const n of placeholders(d.policyText)) {
    const v = (d.values[n] ?? "").trim();
    const err = v ? valueError(n, v) : null;
    if (err) return err;
  }
  return null;
}
/** One edit per policy that changed: the policy only when its text changed, and a value for each placeholder it now uses. */
export function buildEdits(entries: CustomScp[], drafts: Record<string, Draft>): CustomScpEdit[] {
  const edits: CustomScpEdit[] = [];
  for (const e of entries) {
    const d = drafts[e.id];
    if (!d || !isDirty(e, d)) continue;
    const parsed = parsePolicy(d.policyText);
    if ("error" in parsed) throw new Error(`${e.title}: ${parsed.error}`);
    const edit: CustomScpEdit = { id: e.id, values: Object.fromEntries(placeholders(d.policyText).map((n) => [n, (d.values[n] ?? "").trim()])) };
    if (d.policyText !== templateText(e)) edit.policy = parsed.policy;
    edits.push(edit);
  }
  return edits;
}
