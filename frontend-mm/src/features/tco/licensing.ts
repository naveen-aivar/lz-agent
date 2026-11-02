/** The Microsoft licensing comparison: the form answer (pure, so it can be tested) and the shapes of the results. */

export interface LicensingForm {
  compare: boolean;
  coverage: string;
  statement: File | null;
  unit: 'cores' | '2-core packs';
  optimize: boolean;
  enterpriseLicence: string;
  enterpriseSa: string;
  standardLicence: string;
  standardSa: string;
}

export const EMPTY_LICENSING: LicensingForm = {
  compare: false,
  coverage: '',
  statement: null,
  unit: 'cores',
  optimize: false,
  enterpriseLicence: '',
  enterpriseSa: '',
  standardLicence: '',
  standardSa: '',
};

type Amount = { value: number | null } | { error: string };

function amount(raw: string, label: string, max: number): Amount {
  const text = raw.trim();
  if (!text) return { value: null };
  const n = Number(text);
  if (!Number.isFinite(n) || n < 0 || n > max) return { error: `${label} must be a number from 0 to ${max.toLocaleString('en-US')}.` };
  return { value: n };
}

/** What the person entered, as the service expects it. `answer` is null when no comparison was asked for. */
export function buildLicensingAnswer(form: LicensingForm): { answer: Record<string, unknown> | null; error?: string } {
  if (!form.compare) return { answer: null };
  const hasStatement = form.statement !== null;
  if (form.statement && !/\.xlsx$/i.test(form.statement.name)) return { answer: null, error: 'The licence statement must be an .xlsx file.' };
  const coverage = amount(form.coverage, 'Software Assurance coverage', 100);
  if ('error' in coverage) return { answer: null, error: coverage.error };
  if (!hasStatement && coverage.value === null) {
    return { answer: null, error: 'Give the share of SQL Server cores with active Software Assurance, or upload the licence statement.' };
  }
  const answer: Record<string, unknown> = { compare: true, has_statement: hasStatement, optimize_cpu: form.optimize };
  if (coverage.value !== null) answer.sa_coverage_pct = coverage.value;
  if (hasStatement) answer.statement_core_unit = form.unit;
  const editions = [
    ['enterprise', 'Enterprise', form.enterpriseLicence, form.enterpriseSa],
    ['standard', 'Standard', form.standardLicence, form.standardSa],
  ] as const;
  for (const [key, name, licenceRaw, saRaw] of editions) {
    const licence = amount(licenceRaw, `The ${name} licence price`, 1_000_000);
    if ('error' in licence) return { answer: null, error: licence.error };
    const sa = amount(saRaw, `The ${name} Software Assurance price`, 1_000_000);
    if ('error' in sa) return { answer: null, error: sa.error };
    const prices: Record<string, number> = {};
    if (licence.value !== null) prices.licence = licence.value;
    if (sa.value !== null) prices.sa_annual = sa.value;
    if (Object.keys(prices).length) answer[key] = prices;
  }
  return { answer };
}

export interface CostRow {
  label: string;
  annual: number;
  paid_to?: 'aws' | 'microsoft';
}

export interface LicensingScenario {
  name: string;
  rows: CostRow[];
  aws_annual: number;
  microsoft_annual: number;
  total_annual: number;
}

export interface LicensingSummary {
  licence_included: LicensingScenario;
  byol: LicensingScenario;
  difference_annual: number;
  sql_servers: number;
  sql_servers_byol: number;
  sql_servers_free: number;
  licensed_cores: number;
  cores_saved_by_optimize_cpu: number;
  coverage_source: 'entered' | 'statement';
  prices_source: string;
  priced_by: string;
  windows_servers: number;
  end_of_support: string[];
  notes: string[];
  warnings: string[];
}

export interface MapEstimateSummary {
  same_as_main: boolean;
  message: string;
  url?: string | null;
  estimate_annual?: number | null;
  verified: boolean;
  verification?: string | null;
  left_out: string[];
  licence_removed: string[];
}

/** One sentence on which scenario costs less per year. `difference` is licence included minus own licence. */
export function licensingVerdict(difference: number, money: (value: number) => string): string {
  if (Math.abs(difference) < 1) return 'Both scenarios cost about the same per year.';
  if (difference > 0) return `Bringing your own licence costs ${money(difference)} less per year, including the Software Assurance paid to Microsoft.`;
  return `Licence included costs ${money(-difference)} less per year than bringing your own licence with Software Assurance.`;
}
