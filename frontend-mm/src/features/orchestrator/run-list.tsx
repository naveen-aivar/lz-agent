'use client';

import { useEffect, useState } from 'react';
import { ApiError, orchestratorApi, type Run } from '@/features/orchestrator/api';
import { deckName, isFinished, RUN_LABELS } from '@/features/orchestrator/trigger';
import { formatDate } from '@/features/tco/format';
import type { Navigate } from '@/features/agents/types';
import { Notice } from '@/shared/components/notice';
import { PageHeader } from '@/shared/components/page-header';
import { Badge } from '@/shared/design-system/ui/badge';
import { Button } from '@/shared/design-system/ui/button';
import { Card } from '@/shared/design-system/ui/card';
import { SkeletonText } from '@/shared/design-system/ui/skeleton';

const PAGE_SIZE = 20;

export function toneOf(status: string): 'success' | 'danger' | 'default' {
  if (status === 'COMPLETED') return 'success';
  if (status === 'FAILED') return 'danger';
  return 'default';
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.';
}

/** Every deck run, newest first. A run is one click on "Generate decks". */
export function RunList({ navigate }: { navigate: Navigate }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async (reset: boolean) => {
    setError('');
    try {
      const page = await orchestratorApi.listRuns({ limit: PAGE_SIZE, cursor: reset ? null : cursor });
      setRuns((current) => (reset ? page.jobs : current.concat(page.jobs)));
      setCursor(page.next_cursor);
    } catch (caught) {
      setError(caught instanceof ApiError && caught.status === 401 ? 'Sign in again to use this.' : messageOf(caught));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(true);
    // The first page only. Load more is explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="view-enter">
      <PageHeader
        title="Decks"
        description="The final MAP Assess and CVA decks, built from what the other agents produced."
        actions={<Button onClick={() => navigate('new')} disabled={loading}>Generate decks</Button>}
      />
      {error ? (
        <Notice tone="danger" title="The runs could not be loaded." className="mt-4">
          <p>{error}</p>
        </Notice>
      ) : null}
      <Card className="mt-4 overflow-hidden">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">All deck runs</caption>
          <thead className="bg-[var(--color-gray-50)] text-[var(--color-gray-500)]">
            <tr>
              <th className="px-4 py-3 font-medium" scope="col">Customer</th>
              <th className="px-4 py-3 font-medium" scope="col">Decks</th>
              <th className="px-4 py-3 font-medium" scope="col">Status</th>
              <th className="px-4 py-3 font-medium" scope="col">Created</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 8 }, (_, index) => (
                <tr key={index} className="border-t border-[var(--color-gray-100)]">
                  <td className="px-4 py-3"><SkeletonText className="font-medium">Acme Corporation</SkeletonText></td>
                  <td className="px-4 py-3"><SkeletonText>MAP Assess, CVA</SkeletonText></td>
                  <td className="px-4 py-3"><SkeletonText>Completed</SkeletonText></td>
                  <td className="px-4 py-3"><SkeletonText>28 Oct 2026, 15:27</SkeletonText></td>
                </tr>
              ))
            ) : runs.length === 0 ? (
              <tr><td className="px-4 py-6 text-[var(--color-gray-500)]" colSpan={4}>No decks yet. Choose Generate decks to build the first.</td></tr>
            ) : (
              runs.map((run) => (
                <tr key={run.job_id} className="cursor-pointer border-t border-[var(--color-gray-100)] hover:bg-[var(--color-gray-50)]" onClick={() => navigate('run', { id: run.job_id })}>
                  <td className="px-4 py-3">
                    <button type="button" className="font-medium text-[var(--color-primary-700)]" onClick={() => navigate('run', { id: run.job_id })}>
                      {run.customer || 'Customer not named yet'}
                    </button>
                  </td>
                  <td className="px-4 py-3">{run.decks.map(deckName).join(', ')}</td>
                  <td className="px-4 py-3">
                    <Badge variant={toneOf(run.status)}>{run.stalled && !isFinished(run.status) ? 'Stalled' : (RUN_LABELS[run.status] ?? run.status)}</Badge>
                  </td>
                  <td className="px-4 py-3">{formatDate(run.created_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {cursor ? <div className="border-t border-[var(--color-gray-100)] p-3"><Button variant="secondary" size="sm" onClick={() => void load(false)}>Load more</Button></div> : null}
      </Card>
    </div>
  );
}
