/**
 * The trigger: which decks, and which job each source is taken from. The assessment agents hand their files over to the deck
 * service themselves; a person chooses the jobs here and the service reads the files from S3. Pure, so it can be tested without a page.
 */
import type { CreateRunRequest } from '@/features/orchestrator/api';

export interface SourceInfo {
  id: string;
  label: string;
  hint: string;
}

export const SOURCES: readonly SourceInfo[] = [
  { id: 'tco', label: 'TCO', hint: 'The cost assessment.' },
  { id: 'sevenrs', label: '7Rs', hint: 'The 7Rs strategy report.' },
  { id: 'mra', label: 'MRA', hint: 'The migration readiness readout.' },
  { id: 'cva', label: 'CVA', hint: 'The CVA results and inventory.' },
];

export const DECKS: readonly { id: string; label: string; sources: string[] }[] = [
  { id: 'map_assess', label: 'MAP Assess', sources: ['tco', 'sevenrs', 'mra'] },
  { id: 'cva', label: 'CVA', sources: ['cva', 'sevenrs', 'mra'] },
];

export interface TriggerForm {
  customer: string;
  date: string;
  decks: string[];
  /** Source to the chosen job id; empty or missing means the source is not used. */
  picked: Record<string, string | undefined>;
}

export const EMPTY_TRIGGER: TriggerForm = { customer: '', date: '', decks: DECKS.map((deck) => deck.id), picked: {} };

export interface Planned {
  request: CreateRunRequest;
  /** Sources a chosen deck can use that have no job. Their slides will say "Data not available". */
  missingSources: string[];
}

const JOB_ID = /^[0-9a-f]{32}$/;

/** The request to send, or the first thing a person has to fix. */
export function planRun(form: TriggerForm): { plan: Planned } | { error: string } {
  const decks = DECKS.filter((deck) => form.decks.includes(deck.id));
  if (!decks.length) return { error: 'Choose at least one deck.' };
  const customer = form.customer.trim();
  if (customer.length > 80) return { error: 'The customer name can be up to 80 characters.' };
  const date = form.date.trim();
  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) return { error: 'The date must look like 2026-10-28.' };

  const from_jobs: Record<string, string> = {};
  for (const source of SOURCES) {
    const id = (form.picked[source.id] ?? '').trim();
    if (!id) continue;
    if (!JOB_ID.test(id)) return { error: `${source.label}: the job id must be 32 letters and digits.` };
    from_jobs[source.id] = id;
  }
  if (!Object.keys(from_jobs).length) return { error: 'Choose the job to use for at least one source.' };
  if (!decks.some((deck) => deck.sources.some((id) => from_jobs[id]))) {
    return { error: 'None of the chosen jobs is used by the decks you chose. Choose a job for a source the decks use.' };
  }
  if (!customer && !from_jobs.mra) return { error: 'Enter the customer name, or choose an MRA job, which names the customer.' };

  const wanted = new Set(decks.flatMap((deck) => deck.sources));
  const missingSources = SOURCES.filter((source) => wanted.has(source.id) && !from_jobs[source.id]).map((source) => source.label);
  const request: CreateRunRequest = { decks: decks.map((deck) => deck.id), from_jobs };
  if (customer) request.customer = customer;
  if (date) request.date = date;
  return { plan: { request, missingSources } };
}

export const RUN_LABELS: Record<string, string> = {
  CREATED: 'Created',
  QUEUED: 'Queued',
  RUNNING: 'Building the decks',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
};

export const SLIDE_LABELS: Record<string, string> = {
  built: 'Written',
  code: 'Built by code',
  unavailable: 'Data not available',
  failed: 'Could not be built',
};

export const isFinished = (status: string): boolean => status === 'COMPLETED' || status === 'FAILED';

export function deckName(id: string): string {
  return DECKS.find((deck) => deck.id === id)?.label ?? id;
}

export function sourceName(id: string): string {
  return SOURCES.find((source) => source.id === id)?.label ?? id;
}
