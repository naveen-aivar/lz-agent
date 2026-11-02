'use client';

import type { Dispatch, SetStateAction } from 'react';
import { formatMoney, isCalculatorUrl } from '@/features/tco/format';
import {
  licensingVerdict,
  type LicensingForm,
  type LicensingScenario,
  type LicensingSummary,
  type MapEstimateSummary,
} from '@/features/tco/licensing';
import { Card } from '@/shared/design-system/ui/card';

const INPUT = 'mt-1 w-full rounded-[var(--radius-md)] border border-[var(--color-gray-200)] px-3 py-2 text-sm';

/** The Microsoft licensing questions on a new assessment. Shown only when the service says to ask. */
export function LicensingFields({ form, setForm }: { form: LicensingForm; setForm: Dispatch<SetStateAction<LicensingForm>> }) {
  const set = <K extends keyof LicensingForm>(key: K, value: LicensingForm[K]) => setForm((current) => ({ ...current, [key]: value }));
  const price = (id: string, label: string, key: 'enterpriseLicence' | 'enterpriseSa' | 'standardLicence' | 'standardSa', placeholder: string) => (
    <div>
      <label htmlFor={id} className="text-sm">{label}</label>
      <input id={id} className={INPUT} type="number" min={0} step="any" placeholder={placeholder} value={form[key]} onChange={(event) => set(key, event.target.value)} />
    </div>
  );
  return (
    <fieldset className="grid gap-3">
      <legend className="text-sm font-medium">Microsoft licensing comparison (optional)</legend>
      <p className="text-sm text-[var(--color-gray-500)]">
        Compares the same inventory with SQL Server licence included and with the customer’s own licences (which need active Software Assurance). Windows Server stays licence included in both.
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={form.compare} onChange={(event) => set('compare', event.target.checked)} />
        Compare licence included with bring your own licence
      </label>
      {form.compare ? (
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label htmlFor="lic-coverage" className="text-sm">SQL Server cores with active Software Assurance (%)</label>
              <input id="lic-coverage" className={INPUT} type="number" min={0} max={100} step="any" aria-describedby="lic-coverage-hint" value={form.coverage} onChange={(event) => set('coverage', event.target.value)} />
              <p id="lic-coverage-hint" className="mt-1 text-xs text-[var(--color-gray-500)]">Required unless you upload the licence statement.</p>
            </div>
            <div>
              <label htmlFor="lic-statement" className="text-sm">Microsoft License Statement (.xlsx, optional)</label>
              <input id="lic-statement" className="mt-2 block w-full text-sm" type="file" accept=".xlsx" onChange={(event) => set('statement', event.target.files?.[0] ?? null)} />
            </div>
            <fieldset>
              <legend className="text-sm">The statement counts core licences as</legend>
              <div role="radiogroup" className="mt-2 grid gap-1 text-sm">
                {(['cores', '2-core packs'] as const).map((unit) => (
                  <label key={unit} className="flex items-center gap-2">
                    <input type="radio" name="lic-unit" value={unit} checked={form.unit === unit} onChange={() => set('unit', unit)} /> {unit === 'cores' ? 'Cores' : '2-core packs'}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
          <div>
            <p className="text-sm text-[var(--color-gray-500)]">
              Prices per 2-core pack in USD. Leave blank to use Microsoft list prices (indicative): Enterprise $15,123 and $2,793 a year Software Assurance; Standard $3,945 and $728.
            </p>
            <div className="mt-2 grid gap-3 sm:grid-cols-4">
              {price('lic-ent-licence', 'Enterprise licence', 'enterpriseLicence', '15123')}
              {price('lic-ent-sa', 'Enterprise Software Assurance a year', 'enterpriseSa', '2793')}
              {price('lic-std-licence', 'Standard licence', 'standardLicence', '3945')}
              {price('lic-std-sa', 'Standard Software Assurance a year', 'standardSa', '728')}
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.optimize} onChange={(event) => set('optimize', event.target.checked)} />
            License one thread per core (vCPUs ÷ 2). Check with the DBA first.
          </label>
        </div>
      ) : null}
    </fieldset>
  );
}

function ScenarioTable({ scenario }: { scenario: LicensingScenario }) {
  return (
    <div>
      <h3 className="text-sm font-semibold">{scenario.name}</h3>
      <table className="mt-1 w-full text-left text-sm">
        <caption className="sr-only">{scenario.name}, per year</caption>
        <tbody>
          {scenario.rows.map((row) => (
            <tr key={row.label} className="border-b border-[var(--color-gray-200)]">
              <th scope="row" className="py-1.5 pr-3 font-normal">
                {row.label}
                {row.paid_to === 'microsoft' ? <span className="text-[var(--color-gray-500)]"> (Microsoft)</span> : null}
              </th>
              <td className="py-1.5 text-right tabular-nums">{formatMoney(row.annual)}</td>
            </tr>
          ))}
          <tr className="font-semibold">
            <th scope="row" className="py-1.5 pr-3">Total per year</th>
            <td className="py-1.5 text-right tabular-nums">{formatMoney(scenario.total_annual)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function Details({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-sm font-medium">{title}</summary>
      <ul className="mt-2 list-disc pl-5 text-sm">{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </details>
  );
}

/** Both licensing scenarios side by side, with what decides them. */
export function LicensingCard({ licensing }: { licensing: LicensingSummary }) {
  const coverage = licensing.coverage_source === 'statement' ? 'the customer’s licence statement' : 'the share entered for the customer';
  return (
    <Card className="mt-4 p-5">
      <h2 className="text-lg font-semibold">Microsoft licensing: licence included or your own licence</h2>
      <p className="mt-1 text-sm">{licensingVerdict(licensing.difference_annual, formatMoney)}</p>
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <ScenarioTable scenario={licensing.licence_included} />
        <ScenarioTable scenario={licensing.byol} />
      </div>
      <p className="mt-3 text-sm text-[var(--color-gray-700)]">
        {licensing.sql_servers_byol} of {licensing.sql_servers} SQL Server instances are covered by licences with Software Assurance (from {coverage}); {licensing.sql_servers_free} are Express or Developer and need no licence.{' '}
        {licensing.licensed_cores} cores are licensed in the own-licence scenario.
        {licensing.cores_saved_by_optimize_cpu ? ` One thread per core would license ${licensing.cores_saved_by_optimize_cpu} fewer cores.` : ''}
      </p>
      <p className="mt-1 text-xs text-[var(--color-gray-500)]">{licensing.priced_by}. {licensing.prices_source}.</p>
      {licensing.warnings.map((warning) => <p key={warning} className="mt-2 text-sm text-[var(--color-warning-700)]">{warning}</p>)}
      <Details title="End of support" items={licensing.end_of_support} />
      <Details title="How this was worked out" items={licensing.notes} />
    </Card>
  );
}

/** The second calculator estimate (only what AWS MAP can count), or a note that the main one already is. */
export function MapEstimateBlock({ estimate }: { estimate: MapEstimateSummary }) {
  const linked = isCalculatorUrl(estimate.url);
  return (
    <div className="mt-5 border-t border-[var(--color-gray-200)] pt-4">
      <h3 className="text-sm font-semibold">
        MAP-eligible estimate
        {linked ? <span className="ml-2 text-xs font-normal text-[var(--color-gray-500)]">{estimate.verified ? 'Checked against the calculator' : 'Not checked'}</span> : null}
      </h3>
      <p className="mt-1 text-sm">{estimate.message}</p>
      {linked ? (
        <>
          {typeof estimate.estimate_annual === 'number' ? <p className="mt-1 text-sm">Calculator price: {formatMoney(estimate.estimate_annual)} per year.</p> : null}
          <a className="mt-2 inline-block text-sm font-medium text-[var(--color-primary-700)]" href={estimate.url as string} target="_blank" rel="noopener noreferrer">
            Open the MAP-eligible estimate<span className="sr-only"> (opens in a new tab)</span>
          </a>
          {estimate.verification ? <p className="mt-1 text-xs text-[var(--color-gray-500)]">{estimate.verification}</p> : null}
        </>
      ) : null}
      <Details title="Priced without third-party licences" items={estimate.licence_removed} />
      <Details title="Left out (not MAP-eligible)" items={estimate.left_out} />
    </div>
  );
}
