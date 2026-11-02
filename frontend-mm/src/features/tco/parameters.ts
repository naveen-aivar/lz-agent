/**
 * The optional settings on a new assessment, as data: what the form draws and what is sent. The same groups and options as the
 * assessment service's own page. AWS Transform's questions are answered from these; whatever they do not cover is still asked.
 */
export interface Choice {
  value: string;
  label: string;
}

export interface SettingField {
  key: string;
  label: string;
  kind: 'text' | 'number' | 'select' | 'checkbox';
  choices?: Choice[];
  suggestions?: string[];
  placeholder?: string;
  min?: number;
  max?: number;
}

export interface SettingGroup {
  title: string;
  hint?: string;
  fields: SettingField[];
}

const NONE: Choice = { value: '', label: 'Not specified' };
const licence = (label: string): SettingField => ({
  key: label === 'Windows' ? 'windows_licensing' : 'rhel_licensing',
  label: label === 'RHEL' ? 'Red Hat Enterprise Linux' : label,
  kind: 'select',
  choices: [NONE, { value: 'License Included', label: 'License Included' }, { value: 'Bring Your Own License', label: 'Bring your own license' }],
});

export const SETTING_GROUPS: readonly SettingGroup[] = [
  {
    title: 'Region and pricing',
    fields: [
      { key: 'target_region', label: 'AWS region', kind: 'text', placeholder: 'us-east-1' },
      {
        key: 'pricing_model',
        label: 'Pricing model',
        kind: 'text',
        placeholder: 'Reserved Instances, No Upfront',
        suggestions: ['On-Demand', 'Reserved Instances, No Upfront', 'Reserved Instances, Partial Upfront', 'Reserved Instances, All Upfront', 'Compute Savings Plan', 'EC2 Instance Savings Plan'],
      },
      { key: 'payment_option', label: 'Payment option', kind: 'select', choices: [NONE, ...['No Upfront', 'Partial Upfront', 'All Upfront'].map((value) => ({ value, label: value }))] },
      { key: 'tenancy', label: 'Tenancy', kind: 'select', choices: [NONE, { value: 'Shared', label: 'Shared' }, { value: 'Dedicated', label: 'Dedicated' }] },
    ],
  },
  {
    title: 'Licensing',
    fields: [
      licence('Windows'),
      licence('RHEL'),
      {
        key: 'sql_license_model',
        label: 'SQL Server',
        kind: 'select',
        choices: [NONE, { value: 'Bring Your Own Media (BYOM)', label: 'Bring your own media (BYOM)' }, { value: 'License Included', label: 'License Included' }],
      },
    ],
  },
  {
    title: 'Database assumptions',
    hint: 'AWS Transform asks about these when the inventory does not say (SQL Server environment, role and storage).',
    fields: [
      { key: 'use_database_defaults', label: 'Use AWS Transform’s defaults (production, standalone, 500 GB, 100% used)', kind: 'checkbox' },
      { key: 'database_environment', label: 'Environment', kind: 'select', choices: [NONE, { value: 'production', label: 'Production' }, { value: 'non-production', label: 'Non-production' }] },
      { key: 'database_server_role', label: 'Server role', kind: 'select', choices: [NONE, { value: 'standalone', label: 'Standalone' }, { value: 'primary/secondary pairs', label: 'Primary/secondary pairs' }] },
      { key: 'database_provisioned_storage_gb', label: 'Provisioned storage per server (GB)', kind: 'number', min: 1, max: 1_000_000, placeholder: '500' },
      { key: 'database_storage_utilization_pct', label: 'Storage utilization (%)', kind: 'number', min: 0, max: 100, placeholder: '100' },
    ],
  },
  {
    title: 'Utilization',
    fields: [
      { key: 'default_cpu_utilization_pct', label: 'Assumed CPU utilization (%)', kind: 'number', min: 0, max: 100 },
      { key: 'default_memory_utilization_pct', label: 'Assumed memory utilization (%)', kind: 'number', min: 0, max: 100 },
    ],
  },
];

export type SettingValues = Record<string, string | boolean | undefined>;

/** Answer AWS Transform automatically when the settings cover everything it asks. On unless the person turns it off. */
export const DEFAULT_SETTINGS: SettingValues = { auto_answer: true };

const NUMBERS = new Map(SETTING_GROUPS.flatMap((group) => group.fields).filter((field) => field.kind === 'number').map((field) => [field.key, field]));

/** What to send as `parameters`, or the first thing to fix. Blank fields are left out; a ticked box is sent. */
export function buildParameters(values: SettingValues): { parameters: Record<string, string | number | boolean>; error?: string } {
  const parameters: Record<string, string | number | boolean> = {};
  for (const group of SETTING_GROUPS) {
    for (const field of group.fields) {
      const raw = values[field.key];
      if (field.kind === 'checkbox') {
        if (raw === true) parameters[field.key] = true;
        continue;
      }
      const text = typeof raw === 'string' ? raw.trim() : '';
      if (!text) continue;
      if (field.kind !== 'number') {
        parameters[field.key] = text;
        continue;
      }
      const spec = NUMBERS.get(field.key);
      const n = Number(text);
      if (!Number.isFinite(n) || (spec?.min !== undefined && n < spec.min) || (spec?.max !== undefined && n > spec.max)) {
        return { parameters: {}, error: `${field.label} must be a number from ${spec?.min ?? 0} to ${(spec?.max ?? 0).toLocaleString('en-US')}.` };
      }
      parameters[field.key] = n;
    }
  }
  // "Off" is a real choice here, so it is sent; the service's default is on.
  parameters.auto_answer = values.auto_answer !== false;
  return { parameters };
}
