'use client';

import { formatMoney, formatPercent, mapSourceLabel } from '@/features/tco/format';
import type { Summary } from '@/features/tco/api';
import { Card } from '@/shared/design-system/ui/card';

type Map = NonNullable<Summary['map']>;

/** MAP credits: AWS Transform's own RDS credit and any credits entered for the customer, kept apart. */
export function MapCard({ map }: { map: Map }) {
  const items = map.items ?? [];
  const rows: [string, number | undefined][] = [];
  if (items.some((item) => item.source === 'transform')) rows.push(['Credits counted by AWS Transform, per year', map.transform_credit_annual]);
  if (map.entered_credit_annual) {
    rows.push(['Credits entered by you, per year', map.entered_credit_annual]);
    rows.push(['Credits entered by you, over their years', map.entered_credit_total]);
  }
  if (map.recommended_annual != null) rows.push(['Recommended AWS cost per year (AWS Transform, includes its own credit)', map.recommended_annual]);
  if (map.after_entered_annual != null) rows.push(['After the credits you entered, year 1', map.after_entered_annual]);
  const status = map.enrolled === false ? 'The customer is not enrolled in AWS MAP.' : items.length ? null : 'AWS Transform applied no MAP credits.';
  return (
    <Card className="mt-4 p-5">
      <h2 className="text-lg font-semibold">AWS MAP credits</h2>
      {status ? <p className="mt-2 text-sm">{status}</p> : null}
      {items.length ? (
        <table className="mt-3 w-full text-left text-sm">
          <caption className="sr-only">MAP credits by service</caption>
          <thead className="text-[var(--color-gray-500)]">
            <tr>{['Service', 'Credit', 'Source', 'Rate', 'Per year', 'Applies'].map((heading) => <th key={heading} scope="col" className="py-1.5 pr-3 font-medium">{heading}</th>)}</tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.service}-${item.label}`} className="border-t border-[var(--color-gray-100)]">
                <td className="py-1.5 pr-3">{item.service}</td>
                <td className="py-1.5 pr-3">{item.label}</td>
                <td className="py-1.5 pr-3">{mapSourceLabel(item.source)}</td>
                <td className="py-1.5 pr-3">{formatPercent(item.percent)}</td>
                <td className="py-1.5 pr-3 tabular-nums">{formatMoney(item.credit_annual)}</td>
                <td className="py-1.5">{item.applies}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {rows.length ? (
        <table className="mt-3 w-full text-left text-sm">
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label} className="border-b border-[var(--color-gray-100)]">
                <th scope="row" className="py-1.5 pr-3 font-normal">{label}</th>
                <td className="py-1.5 text-right tabular-nums">{formatMoney(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {(map.warnings ?? []).map((warning) => <p key={warning} className="mt-2 text-sm text-[var(--color-danger-700)]">{warning}</p>)}
      <p className="mt-3 text-xs text-[var(--color-gray-500)]">Estimates. MAP credits depend on the customer’s MAP agreement; rows marked as entered use the percentages given when the assessment was created.</p>
    </Card>
  );
}
