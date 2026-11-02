export interface CvaRunRow {
  run_id: string;
  label?: string;
  finalised?: boolean;
  files?: string[];
}

export interface CvaScenario {
  id: string;
  label: string;
  total: number | null;
  status: string;
  source?: string;
  notes?: string[];
}

export interface CvaCheck {
  id: string;
  ok: boolean;
  title: string;
  detail: string;
}

export interface CvaOverview {
  gate: { ready: boolean; open: number; checks: CvaCheck[] };
  finalised: false | { by: string; ts: string };
  manifest: { label?: string };
  estate: { files: string[]; workloads: number };
  meta: {
    figures_source?: string;
    lifecycle_rules_unverified?: boolean;
    richness: { grade: string; label: string; peak_coverage: number; memory_coverage: number; reasons: string[] };
  };
  scenarios: CvaScenario[];
  commentary: { executive_summary: { text: string; source: string } };
  aws?: { scenario?: string } | null;
  sizing_source?: string | null;
  estimate_ran?: boolean;
  licensing: { mode: string };
  figures?: Record<string, number | string | null>;
  kpis: {
    proposals: { accepted: number; rejected: number; pending: number };
    analyst_hours_logged: number | null;
    turnaround_hours: number | null;
    llm_calls: number;
    tokens_in: number;
    tokens_out: number;
    first_pass_accepted?: boolean | null;
  };
}

export const CVA_STAGES = [
  { id: 'overview', label: 'Overview' },
  { id: 'transform', label: 'AWS Transform' },
  { id: 'workloads', label: 'Workloads' },
  { id: 'licensing', label: 'Licensing' },
  { id: 'exceptions', label: 'Exceptions' },
  { id: 'agent', label: 'Agent' },
  { id: 'review', label: 'Review' },
  { id: 'outputs', label: 'Outputs' },
  { id: 'audit', label: 'Audit' },
] as const;

export type CvaStage = (typeof CVA_STAGES)[number]['id'];

export function money(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return 'n/a';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
}
