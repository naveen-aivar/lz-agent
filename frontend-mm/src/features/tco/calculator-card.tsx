'use client';

import { formatMoney, isCalculatorUrl, reconcilingLabel } from '@/features/tco/format';
import type { Summary } from '@/features/tco/api';
import { MapEstimateBlock } from '@/features/tco/licensing-panels';
import { Badge } from '@/shared/design-system/ui/badge';
import { Card } from '@/shared/design-system/ui/card';

type Calculator = NonNullable<Summary['calculator']>;

const UNVERIFIED = 'Unverified: the estimate has not been compared with the calculator’s own computed prices. The costs above are AWS Transform’s costs for the same rows.';

/** The AWS Pricing Calculator estimate, how its total ties back to AWS Transform's figure, and the MAP-eligible estimate. */
export function CalculatorCard({ calculator }: { calculator: Calculator }) {
  if (!isCalculatorUrl(calculator.url)) return null;
  const rows: [string, number | undefined][] = [['Estimate', calculator.estimate_annual]];
  for (const [key, value] of Object.entries(calculator.reconciling ?? {})) rows.push([reconcilingLabel(key), value]);
  if (calculator.transform_recommended_annual != null) rows.push(['AWS Transform recommended annual cost', calculator.transform_recommended_annual]);
  const unreconciled = (calculator.unreconciled ?? []).join(', ');
  return (
    <Card className="mt-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">
          AWS Pricing Calculator <Badge variant={calculator.verified ? 'success' : 'warning'} className="ml-2 align-middle">{calculator.verified ? 'Verified' : 'Unverified'}</Badge>
        </h2>
        <a className="text-sm font-medium text-[var(--color-primary-700)]" href={calculator.url} target="_blank" rel="noopener noreferrer">
          Open the estimate<span className="sr-only"> (opens in a new tab)</span>
        </a>
      </div>
      <table className="mt-3 w-full text-left text-sm">
        <caption className="sr-only">How the calculator estimate reconciles with AWS Transform, per year</caption>
        <tbody>
          {rows.map(([label, value], index) => (
            <tr key={label} className={`border-b border-[var(--color-gray-100)] ${index === rows.length - 1 && calculator.transform_recommended_annual != null ? 'font-semibold' : ''}`}>
              <th scope="row" className="py-1.5 pr-3 font-normal">{label}</th>
              <td className="py-1.5 text-right tabular-nums">{formatMoney(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {calculator.decisions?.length ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-medium">Pricing choices mapped from AWS Transform (please review)</summary>
          <ul className="mt-2 list-disc pl-5 text-sm">
            {calculator.decisions.map((decision) => (
              <li key={decision.setting}>{decision.setting} <span className="text-[var(--color-gray-500)]">Based on: “{decision.evidence}”</span></li>
            ))}
          </ul>
        </details>
      ) : null}
      {unreconciled ? <p className="mt-3 text-sm text-[var(--color-danger-700)]">These parts do not add up to AWS Transform’s figures: {unreconciled}.</p> : null}
      <p className="mt-3 text-xs text-[var(--color-gray-500)]">{calculator.verification ?? UNVERIFIED}</p>
      <p className="mt-1 text-xs text-[var(--color-gray-500)]">Anyone with the link can view the estimate. Calculator prices change over time; open it to see current prices.</p>
      {calculator.map_estimate ? <MapEstimateBlock estimate={calculator.map_estimate} /> : null}
    </Card>
  );
}
