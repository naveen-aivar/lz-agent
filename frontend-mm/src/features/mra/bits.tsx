import { Badge } from '@/shared/design-system/ui/badge';

import type { ScoreGroup } from '@/features/mra/types';

export function when(value: string | undefined): string {
  return (value || '').replace('T', ' ').replace(/\+00:00$/, ' UTC');
}

export function colourVariant(colour: string): 'success' | 'warning' | 'danger' | 'muted' {
  if (colour === 'green') return 'success';
  if (colour === 'amber') return 'warning';
  if (colour === 'red') return 'danger';
  return 'muted';
}

export function colourLabel(colour: string): string {
  return colour === 'incomplete' ? 'Incomplete' : colour;
}

export function scoreLabel(group: { status: string; score: number | null }): string {
  return group.status === 'complete' && group.score !== null ? group.score.toFixed(1) : 'Incomplete';
}

const BAR: Record<string, string> = { green: 'var(--color-success-700)', amber: 'var(--color-warning-700)', red: 'var(--color-danger-700)' };

export function ScoreTable({ title, rows }: { title: string; rows: ScoreGroup[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-[var(--color-gray-500)]">
              {['Name', 'Score', '', 'Rated'].map((heading, index) => (
                <th key={`${heading}-${index}`} className="py-2 pr-3 font-medium">{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((group) => (
              <tr key={group.name} className="border-t border-[var(--color-gray-100)]">
                <td className="py-2 pr-3">{group.name}</td>
                <td className="py-2 pr-3">
                  {scoreLabel(group)} <Badge variant={colourVariant(group.colour)}>{colourLabel(group.colour)}</Badge>
                </td>
                <td className="w-32 py-2 pr-3">
                  {group.status === 'complete' ? (
                    <span className="mra-bar block h-2 overflow-hidden rounded-full bg-[var(--color-gray-100)]">
                      <span className="block h-full" style={{ width: `${Math.max(0, Math.min(100, ((group.score ?? 0) / 5) * 100))}%`, background: BAR[group.colour] || 'var(--color-gray-300)' }} />
                    </span>
                  ) : (
                    <span className="text-[var(--color-gray-500)]">A rating is blank</span>
                  )}
                </td>
                <td className="py-2">{group.answered} of {group.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
