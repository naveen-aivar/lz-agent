import { describe, expect, it } from 'vitest';

import { buildAnswer, type PendingInput } from '@/features/tco/answer';
import { buildMapAnswer } from '@/features/tco/map';
import { personStep } from '@/features/tco/format';

const pending: PendingInput = {
  request_id: 'r1',
  kind: 'scenario_confirmation',
  message: 'Confirm the region.',
  fields: [{ key: 'region', label: 'Region', type: 'text', required: true, default: 'us-east-1' }],
};

describe('assessment answers', () => {
  it('keeps a default as proceed and a change as change', () => {
    expect(buildAnswer(pending, { region: 'us-east-1' }, '')).toEqual({ answer: { request_id: 'r1', values: { region: 'us-east-1' }, decision: 'proceed' } });
    expect(buildAnswer(pending, { region: 'eu-west-1' }, 'note')).toEqual({
      answer: { request_id: 'r1', values: { region: 'eu-west-1' }, decision: 'change', free_text: 'note' },
    });
  });

  it('rejects a missing required field', () => {
    expect(buildAnswer(pending, { region: '  ' }, '')).toEqual({ errors: { region: 'Region is required.' } });
  });

  it('maps the five things a person does onto the service statuses', () => {
    expect(personStep('UPLOADED')).toBe(0);
    expect(personStep('RUNNING_INGEST')).toBe(1);
    expect(personStep('NEEDS_INPUT')).toBe(2);
    expect(personStep('RUNNING_ASSESS')).toBe(3);
    expect(personStep('COMPLETED')).toBe(4);
    expect(personStep('FAILED')).toBe(-1);
  });
});

describe('migration credits', () => {
  it('sends enrolled false, nothing, or the entered credits', () => {
    expect(buildMapAnswer({ choice: 'no', ec2: '', ebs: '', years: '' })).toEqual({ answer: { enrolled: false } });
    expect(buildMapAnswer({ choice: '', ec2: '', ebs: '', years: '' })).toEqual({ answer: null });
    expect(buildMapAnswer({ choice: 'yes', ec2: '15', ebs: '', years: '' })).toEqual({
      answer: { enrolled: true, ec2_credit_pct: 15, ebs_credit_pct: 0, credit_years: 1 },
    });
  });

  it('rejects a credit outside 0 to 100', () => {
    expect(buildMapAnswer({ choice: 'yes', ec2: '150', ebs: '', years: '1' }).error).toMatch(/0 to 100/);
  });
});
