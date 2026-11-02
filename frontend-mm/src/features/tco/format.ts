/** Display helpers. Stored values stay UTC ISO 8601; a person sees them only here. */

const STATUS_LABELS: Record<string, string> = {
  CREATED: 'Created',
  UPLOADED: 'Uploaded',
  QUEUED: 'Queued',
  RUNNING_INGEST: 'Reading the inventory',
  NEEDS_INPUT: 'Needs your answer',
  RUNNING_ASSESS: 'Comparing costs',
  COLLECTING: 'Collecting results',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
};

const OUTPUT_LABELS: Record<string, string> = {
  deck: 'Slide deck',
  deck_pdf: 'Slide deck (PDF)',
  summary: 'Results summary',
  aggregated: 'Full results',
  errors: 'Data warnings',
  bundle: 'Report bundle',
  calculator: 'Pricing calculator check',
  licensing: 'Microsoft licensing comparison',
};

const OUTPUT_ORDER = ['deck', 'deck_pdf', 'summary', 'calculator', 'licensing', 'aggregated', 'errors', 'bundle'];

const CALCULATOR_URL = /^https:\/\/calculator\.aws\/#\/estimate\?id=[0-9a-f]{20,64}$/;

export function isCalculatorUrl(url: unknown): url is string {
  return typeof url === 'string' && CALCULATOR_URL.test(url);
}

const RECONCILING_LABELS: Record<string, string> = {
  network: 'Network',
  support: 'Support',
  credits: 'Migration credits',
  rds_backup: 'Database backup storage',
};

export function reconcilingLabel(key: string): string {
  if (RECONCILING_LABELS[key]) return RECONCILING_LABELS[key];
  if (key.startsWith('not_modelled:')) return `Not in the estimate: ${key.slice(13)}`;
  return key;
}

export function outputLabel(label: string): string {
  return OUTPUT_LABELS[label] ?? label;
}

export function sortOutputs<T extends { label: string }>(files: T[]): T[] {
  const rank = (file: T) => {
    const index = OUTPUT_ORDER.indexOf(file.label);
    return index === -1 ? OUTPUT_ORDER.length : index;
  };
  return [...files].sort((a, b) => rank(a) - rank(b));
}

export const TERMINAL = new Set(['COMPLETED', 'FAILED']);

/** What the person does, in order. The service's own status names sit behind these. */
export const PERSON_STEPS = [
  { id: 'upload', label: 'Upload' },
  { id: 'read', label: 'Read the inventory' },
  { id: 'answers', label: 'Your answers' },
  { id: 'compare', label: 'Compare costs' },
  { id: 'results', label: 'Results' },
] as const;

export function personStep(status: string): number {
  if (status === 'CREATED' || status === 'UPLOADED' || status === 'QUEUED') return status === 'QUEUED' ? 1 : 0;
  if (status === 'RUNNING_INGEST') return 1;
  if (status === 'NEEDS_INPUT') return 2;
  if (status === 'RUNNING_ASSESS' || status === 'COLLECTING') return 3;
  if (status === 'COMPLETED') return 4;
  return -1;
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function isActive(status: string): boolean {
  return !TERMINAL.has(status) && status !== 'CREATED';
}

export function formatDate(iso: string | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export function formatMoney(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n)) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const MAP_SOURCES: Record<string, string> = { transform: 'From the assessment', entered: 'Entered by you' };

export function mapSourceLabel(source: string): string {
  return MAP_SOURCES[source] ?? source;
}

export function formatPercent(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${Number(value.toFixed(2))}%` : '';
}

export function elapsed(iso: string | undefined, now = Date.now()): string {
  if (!iso) return '';
  const start = new Date(iso).getTime();
  if (Number.isNaN(start)) return '';
  const seconds = Math.max(0, Math.floor((now - start) / 1000));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 1) return `${rest}s`;
  return `${minutes}m ${rest.toString().padStart(2, '0')}s`;
}

export const PROGRESS_TEXT: Record<string, string> = {
  CREATED: 'Waiting to start.',
  UPLOADED: 'Waiting to start.',
  QUEUED: 'Waiting in the queue.',
  RUNNING_INGEST: 'Reading the inventory file.',
  NEEDS_INPUT: 'Waiting for your answer.',
  RUNNING_ASSESS: 'Comparing what you pay today with what AWS would cost. This can take several minutes.',
  COLLECTING: 'Collecting the results and building the deck.',
};
