import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { hasNoteField, type PendingInput } from '@/features/tco/answer';
import { buildLicensingAnswer, EMPTY_LICENSING, licensingVerdict, type LicensingSummary } from '@/features/tco/licensing';
import { LicensingCard, MapEstimateBlock } from '@/features/tco/licensing-panels';

const ask = { ...EMPTY_LICENSING, compare: true };
const statement = (name: string) => new File(['x'], name);

describe('the licensing answer', () => {
  it('sends nothing when no comparison was asked for', () => {
    expect(buildLicensingAnswer(EMPTY_LICENSING)).toEqual({ answer: null });
  });
  it('needs a coverage share or a statement, and keeps the share within 0 to 100', () => {
    expect(buildLicensingAnswer(ask).error).toMatch(/Software Assurance/);
    expect(buildLicensingAnswer({ ...ask, coverage: '120' }).error).toMatch(/0 to 100/);
  });
  it('lets a statement replace the share and carries its core unit', () => {
    expect(buildLicensingAnswer({ ...ask, statement: statement('mls.xlsx'), unit: '2-core packs' }).answer).toEqual({
      compare: true,
      has_statement: true,
      optimize_cpu: false,
      statement_core_unit: '2-core packs',
    });
    expect(buildLicensingAnswer({ ...ask, statement: statement('mls.csv') }).error).toMatch(/xlsx/);
  });
  it('sends only the prices that were entered', () => {
    expect(buildLicensingAnswer({ ...ask, coverage: '60', enterpriseSa: '2500', optimize: true }).answer).toEqual({
      compare: true,
      has_statement: false,
      optimize_cpu: true,
      sa_coverage_pct: 60,
      enterprise: { sa_annual: 2500 },
    });
    expect(buildLicensingAnswer({ ...ask, coverage: '60', standardLicence: '-1' }).error).toMatch(/Standard licence price/);
  });
});

describe('the question form', () => {
  it('needs no second notes box when the service asks for its own', () => {
    const base: PendingInput = { request_id: 'r', message: 'm', allow_free_text: true, fields: [] };
    const notes = { key: 'notes', label: 'Changes or notes (optional)', type: 'text', required: false };
    expect(hasNoteField({ ...base, fields: [notes] })).toBe(true);
    expect(hasNoteField(base)).toBe(false);
    expect(hasNoteField({ ...base, fields: [{ ...notes, required: true }] })).toBe(false);
  });
});

const scenario = (name: string, total: number, microsoft = 0) => ({
  name,
  rows: [{ label: 'EC2', annual: total - microsoft }, ...(microsoft ? [{ label: 'SQL Server Software Assurance kept (paid to Microsoft)', annual: microsoft, paid_to: 'microsoft' as const }] : [])],
  aws_annual: total - microsoft,
  microsoft_annual: microsoft,
  total_annual: total,
});
const summary: LicensingSummary = {
  licence_included: scenario('Licence included', 1000),
  byol: scenario('Bring your own licence', 900, 200),
  difference_annual: 100,
  sql_servers: 10,
  sql_servers_byol: 6,
  sql_servers_free: 2,
  licensed_cores: 24,
  cores_saved_by_optimize_cpu: 0,
  coverage_source: 'entered',
  prices_source: 'list prices',
  priced_by: 'AWS Transform’s costs',
  windows_servers: 5,
  end_of_support: ['Windows Server 2012: support ended.'],
  notes: [],
  warnings: ['Coverage was entered, not read from a statement.'],
};

describe('the licensing results', () => {
  it('says which scenario costs less and keeps Microsoft’s cost apart', () => {
    expect(licensingVerdict(100, (v) => `$${v}`)).toMatch(/own licence costs \$100 less/);
    expect(licensingVerdict(-50, (v) => `$${v}`)).toMatch(/Licence included costs \$50 less/);
    expect(licensingVerdict(0.2, (v) => `$${v}`)).toMatch(/about the same/);
    render(<LicensingCard licensing={summary} />);
    expect(screen.getByText('Licence included')).toBeInTheDocument();
    expect(screen.getByText(/\(Microsoft\)/)).toBeInTheDocument();
    expect(screen.getByText('Coverage was entered, not read from a statement.')).toBeInTheDocument();
  });
  it('shows a message and no link when the main estimate is already MAP-eligible', () => {
    render(<MapEstimateBlock estimate={{ same_as_main: true, message: 'Same estimate.', verified: false, left_out: [], licence_removed: [] }} />);
    expect(screen.getByText('Same estimate.')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
  });
  it('links only calculator.aws estimates', () => {
    const base = { same_as_main: false, message: 'MAP only.', verified: true, left_out: [], licence_removed: [] };
    const { rerender } = render(<MapEstimateBlock estimate={{ ...base, url: 'https://calculator.aws/#/estimate?id=' + 'a'.repeat(40) }} />);
    expect(screen.getByRole('link')).toHaveAttribute('href', expect.stringContaining('calculator.aws'));
    rerender(<MapEstimateBlock estimate={{ ...base, url: 'https://evil.example/#/estimate' }} />);
    expect(screen.queryByRole('link')).toBeNull();
  });
});
