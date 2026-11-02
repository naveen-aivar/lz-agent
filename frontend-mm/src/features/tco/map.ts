/** The optional migration-credit answers on a new assessment. */

export function buildMapAnswer(fields: { choice: string; ec2: string; ebs: string; years: string }): { answer: Record<string, unknown> | null; error?: string } {
  if (fields.choice === 'no') return { answer: { enrolled: false } };
  if (fields.choice !== 'yes') return { answer: null };
  const percent = (raw: string, label: string): { value: number } | { error: string } => {
    const text = raw.trim();
    if (!text) return { value: 0 };
    const n = Number(text);
    if (!Number.isFinite(n) || n < 0 || n > 100) return { error: `${label} must be a number from 0 to 100.` };
    return { value: n };
  };
  const ec2 = percent(fields.ec2, 'The compute credit');
  if ('error' in ec2) return { answer: null, error: ec2.error };
  const ebs = percent(fields.ebs, 'The storage credit');
  if ('error' in ebs) return { answer: null, error: ebs.error };
  const years = fields.years.trim() === '' ? 1 : Number(fields.years);
  if (!Number.isInteger(years) || years < 1 || years > 5) return { answer: null, error: 'Credit years must be a whole number from 1 to 5.' };
  return { answer: { enrolled: true, ec2_credit_pct: ec2.value, ebs_credit_pct: ebs.value, credit_years: years } };
}
