/** The question form, with no page of its own, so it can be tested on its own. */

export interface PendingField {
  key: string;
  label: string;
  type: 'enum' | 'boolean' | 'number' | 'text' | string;
  required?: boolean;
  options?: string[];
  default?: unknown;
  min?: number | null;
  max?: number | null;
}

export interface PendingInput {
  request_id: string;
  kind?: string;
  message: string;
  fields: PendingField[];
  allow_free_text?: boolean;
}

/** True when the form already has its own optional text field for notes or changes, so no second box is needed. */
export function hasNoteField(pending: PendingInput): boolean {
  return pending.fields.some((field) => field.type === 'text' && !field.required && /note|change|comment/i.test(`${field.key} ${field.label}`));
}
export function parseFieldValue(field: PendingField, raw: unknown): unknown {
  if (field.type === 'boolean') return raw === true || raw === 'true' || raw === 'on';
  if (field.type === 'number') {
    if (raw === '' || raw === null || raw === undefined) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : Number.NaN;
  }
  const text = String(raw ?? '').trim();
  return text === '' ? null : text;
}

export function validateField(field: PendingField, value: unknown): string {
  if (value === null || value === undefined) return field.required ? `${field.label} is required.` : '';
  if (field.type === 'number') {
    if (typeof value !== 'number' || Number.isNaN(value)) return `${field.label} must be a number.`;
    if (field.min !== null && field.min !== undefined && value < field.min) return `${field.label} must be at least ${field.min}.`;
    if (field.max !== null && field.max !== undefined && value > field.max) return `${field.label} must be at most ${field.max}.`;
  }
  if (field.type === 'enum' && !(field.options ?? []).includes(String(value))) return `${field.label} must be one of the options.`;
  if (field.type === 'text' && String(value).length > 200) return `${field.label} is too long.`;
  return '';
}

/** Build the answer the service expects, or the field errors to show. */
export function buildAnswer(
  pending: PendingInput,
  rawValues: Record<string, unknown>,
  freeText: string,
): { answer: Record<string, unknown> } | { errors: Record<string, string> } {
  const values: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const field of pending.fields) {
    const value = parseFieldValue(field, rawValues[field.key]);
    const problem = validateField(field, value);
    if (problem) errors[field.key] = problem;
    else if (value !== null) values[field.key] = value;
  }
  if (Object.keys(errors).length) return { errors };
  const changed = pending.fields.some((field) => field.default !== undefined && field.default !== null && values[field.key] !== field.default);
  const answer: Record<string, unknown> = { request_id: pending.request_id, values, decision: changed ? 'change' : 'proceed' };
  const note = freeText.trim();
  if (note) answer.free_text = note.slice(0, 1000);
  return { answer };
}
