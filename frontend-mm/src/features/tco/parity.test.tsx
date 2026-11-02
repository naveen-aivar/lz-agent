import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CalculatorCard } from '@/features/tco/calculator-card';
import { ActivityTimeline } from '@/features/tco/detail-panels';
import { HandoverCard } from '@/features/tco/handover-card';
import { MapCard } from '@/features/tco/map-card';
import { buildParameters, DEFAULT_SETTINGS, SETTING_GROUPS } from '@/features/tco/parameters';
import { AssessmentDetail, NewAssessment } from '@/features/tco/screens';

const URL = 'https://calculator.aws/#/estimate?id=' + 'a'.repeat(40);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

afterEach(() => vi.unstubAllGlobals());

describe('the settings of a new assessment', () => {
  it('sends nothing for blank fields and turns automatic answers on by default', () => {
    expect(buildParameters(DEFAULT_SETTINGS)).toEqual({ parameters: { auto_answer: true } });
  });
  it('sends what was filled in, a ticked box, and an explicit off for automatic answers', () => {
    const built = buildParameters({ target_region: ' eu-west-1 ', payment_option: 'No Upfront', sql_license_model: 'License Included', use_database_defaults: true, database_provisioned_storage_gb: '800', auto_answer: false });
    expect(built.parameters).toEqual({
      target_region: 'eu-west-1',
      payment_option: 'No Upfront',
      sql_license_model: 'License Included',
      use_database_defaults: true,
      database_provisioned_storage_gb: 800,
      auto_answer: false,
    });
  });
  it('refuses a number outside its range and names the field', () => {
    expect(buildParameters({ default_cpu_utilization_pct: '150' }).error).toMatch(/Assumed CPU utilization.*0 to 100/);
    expect(buildParameters({ database_provisioned_storage_gb: '0' }).error).toMatch(/Provisioned storage/);
  });
  it('has no on-premises setting', () => {
    const keys = SETTING_GROUPS.flatMap((group) => group.fields.map((field) => field.key));
    expect(keys.filter((key) => /onprem|on_prem/.test(key))).toEqual([]);
  });
  it('draws the groups of the service’s own page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ features: {} })));
    render(<NewAssessment navigate={() => {}} />);
    await userEvent.setup().click(screen.getByText(/^Optional settings \(/));
    for (const title of ['Region and pricing', 'Licensing', 'Database assumptions', 'Utilization']) expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByLabelText('Payment option')).toBeInTheDocument();
    expect(screen.getByLabelText('SQL Server')).toBeInTheDocument();
    expect(screen.queryByText(/discount/i)).toBeNull();
  });
});

describe('what the results never show', () => {
  it('leaves out the cost today and the saving even when the service still sends it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).endsWith('/outputs')) return json({ files: [] });
        return json({
          job_id: 'j1', status: 'COMPLETED', original_filename: 'inv.xlsx',
          summary: { servers_in_scope: 3, servers_total: 4, onprem_annual_cost: 999999, pricing_models: [{ name: 'On-Demand', annual_aws_cost: 1200, recommended: true }] },
        });
      }),
    );
    render(<AssessmentDetail id="j1" />);
    await waitFor(() => expect(screen.getByText('Recommended AWS per year')).toBeInTheDocument());
    expect(screen.getByText('Servers in scope')).toBeInTheDocument();
    expect(screen.queryByText(/What you pay/)).toBeNull();
    expect(screen.queryByText(/saving/i)).toBeNull();
    expect(screen.queryByText(/999,999/)).toBeNull();
  });
});

describe('the calculator card', () => {
  const base = { url: URL, estimate_annual: 1000, reconciling: { support: 50 }, transform_recommended_annual: 1050 };
  it('says verified or unverified, with the sentence the service gave', () => {
    const { rerender } = render(<CalculatorCard calculator={{ ...base, verified: true, verification: 'Verified: prices match.' }} />);
    expect(screen.getByText('Verified')).toBeInTheDocument();
    expect(screen.getByText('Verified: prices match.')).toBeInTheDocument();
    rerender(<CalculatorCard calculator={{ ...base, verified: false }} />);
    expect(screen.getByText('Unverified')).toBeInTheDocument();
    expect(screen.getByText(/has not been compared/)).toBeInTheDocument();
  });
  it('shows the estimate against Transform’s figure, the pricing choices to review and groups that do not add up', () => {
    render(<CalculatorCard calculator={{ ...base, verified: true, unreconciled: ['database'], decisions: [{ setting: 'Savings plan', evidence: '80% coverage' }] }} />);
    expect(screen.getByText('Estimate')).toBeInTheDocument();
    expect(screen.getByText('AWS Transform recommended annual cost')).toBeInTheDocument();
    expect(screen.getByText(/Pricing choices mapped from AWS Transform/)).toBeInTheDocument();
    expect(screen.getByText(/do not add up to AWS Transform’s figures: database/)).toBeInTheDocument();
  });
  it('shows nothing for a link that is not a calculator estimate', () => {
    const { container } = render(<CalculatorCard calculator={{ ...base, url: 'https://evil.example/' }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('the MAP card', () => {
  it('shows each credit with its source and the totals', () => {
    render(
      <MapCard map={{ enrolled: true, items: [{ service: 'RDS', label: 'MAP Lite', source: 'transform', percent: 15, credit_annual: 22000, applies: 'all years' }], transform_credit_annual: 22000, recommended_annual: 100000 }} />,
    );
    expect(screen.getByText('MAP Lite')).toBeInTheDocument();
    expect(screen.getByText('Credits counted by AWS Transform, per year')).toBeInTheDocument();
    expect(screen.getByText(/Recommended AWS cost per year/)).toBeInTheDocument();
  });
  it('shows the job id to pick in the deck orchestrator', () => {
    const id = 'a1'.repeat(16);
    render(<HandoverCard handover={{ job_id: id, files: [{ slot: 'tco.aggregated', filename: 'aggregated_output.json', size: 10 }] }} />);
    expect(screen.getByText(id)).toBeInTheDocument();
    expect(screen.getByText(/aggregated_output\.json/)).toBeInTheDocument();
  });
  it('says so when the customer is not enrolled', () => {
    render(<MapCard map={{ enrolled: false, items: [] }} />);
    expect(screen.getByText('The customer is not enrolled in AWS MAP.')).toBeInTheDocument();
  });
});

describe('the timeline', () => {
  it('lists what was sent to AWS Transform under the step that sent it', async () => {
    render(<ActivityTimeline running={false} events={[{ ts: '2026-10-30T01:00:00Z', message: 'Answered AWS Transform', detail: { sent: { region: 'us-east-1', tenancy: 'Shared' } } }]} />);
    await waitFor(() => expect(screen.getByLabelText('Sent to AWS Transform')).toBeInTheDocument());
    expect(screen.getByText(/region:/)).toBeInTheDocument();
    expect(screen.getByText('Shared')).toBeInTheDocument();
  });
});
