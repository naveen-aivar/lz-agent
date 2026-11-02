export interface ScoreGroup {
  name: string;
  status: string;
  score: number | null;
  colour: string;
  answered: number;
  total: number;
}

export interface MraQuestion {
  question_id: string;
  category: string;
  activity: string;
  text: string;
  score: number | null;
  levels: string[];
  level_text: string;
  perspective?: string;
  adjusted?: boolean;
  original_score?: number;
  adjustment?: { reason: string };
  traceable?: boolean;
}

export interface MraAction {
  text: string;
  source?: string;
  owner?: string;
  due_date?: string;
  status?: string;
}

export interface MraActivity {
  id: string;
  name: string;
  colour: string;
  score: number | null;
  status: string;
  phase: string;
  needs_action: boolean;
  decision: string;
  comment?: string;
  workstream_name: string;
  observation: { text: string; source?: string };
  actions: MraAction[];
}

export interface MraValidation {
  key: string;
  item_id: string;
  kind: string;
  reason: string;
  resolution: string;
  note?: string;
  followup?: { audience_roles: string[]; questions: string[] };
}

export interface MraProposal {
  id: string;
  kind: string;
  task: string;
  status: string;
  payload: Record<string, unknown>;
  excerpt?: { found: boolean; before: string; quote: string; after: string } | null;
  decision?: { by: string; at: string; comment?: string } | null;
}

export interface MraRun {
  set_id: string;
  customer: string;
  report_status: string;
  generated_at: string;
  engine: string;
  blank_ratings: string[];
  input_warnings: string[];
  narrative: { text: string; source?: string };
  perspectives: ScoreGroup[];
  workstreams: ScoreGroup[];
  focus: {
    perspective_sentences: string[];
    workstream_sentences: string[];
    strengths: string[];
    gaps: string[];
    key_observations: { strong: string[]; weak: string[] }[];
  };
  traceability: { evidenced: number; scored_questions: number; evidenced_pct: number | null };
  notes: { id: string; source: string; applies_to: string[]; text: string }[];
  placeholder_notes: string[];
  questions: MraQuestion[];
  activities: MraActivity[];
  validation: MraValidation[];
  proposals: MraProposal[];
  text_answers: { number: string; category: string; question: string; answer: string }[];
  status: {
    final: { by: string; at: string } | null;
    ready_to_finalise: boolean;
    blockers: string[];
    scores_confirmation_stale: boolean;
    scores_confirmed: boolean;
    blank_ratings: number;
    actions_decided: number;
    actions_total: number;
    items_resolved: number;
    items_total: number;
  };
  details: Record<string, string>;
  exports: { name: string; size: number; url: string }[];
  kpis: {
    turnaround: { hours: number | null; note: string };
    evidence_traceability: { at_first_run_pct: number; now_pct: number };
    validation_items: { at_first_run: number; now: number; resolved: number };
    agent_proposals: { acceptance_rate_pct: number | null };
  };
  audit: { entries: number; ok: boolean; problem?: string };
}

export interface MraRunRow {
  customer: string;
  set_id: string;
  final: boolean;
  blank_ratings: number | string;
  engine: string;
  generated_at: string;
}

export interface DeckTemplate {
  id: string;
  name: string;
  builtin?: boolean;
  description?: string;
  coverage?: { complete: boolean; found: number; expected: number; warnings: string[]; format?: string; items: { label: string; ok: boolean; found: string; expected: string }[] };
}

export interface MraInfo {
  version: string;
  engine: string;
  model_id: string;
  storage: string;
  storage_where: string;
  config_hash: string;
  libreoffice: boolean;
  hosted?: boolean;
  meta_fields: string[];
  placeholder_notes: string[];
  user?: { can_write: boolean };
  templates: { pptx: { preferred: string; templates: DeckTemplate[] }; docx: string | null };
}

export const MRA_STAGES = [
  { id: 'overview', label: 'Overview' },
  { id: 'ratings', label: 'Ratings' },
  { id: 'activities', label: 'Activities' },
  { id: 'validation', label: 'Validation' },
  { id: 'proposals', label: 'Proposals' },
  { id: 'answers', label: 'Answers' },
  { id: 'release', label: 'Release' },
  { id: 'outputs', label: 'Outputs' },
] as const;

export type MraStage = (typeof MRA_STAGES)[number]['id'];
