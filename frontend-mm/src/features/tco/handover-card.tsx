'use client';
import type { Summary } from '@/features/tco/api';
import { Card } from '@/shared/design-system/ui/card';

type Handover = NonNullable<Summary['handover']>;

/** The results were handed over to the deck orchestrator: the job id to pick there. */
export function HandoverCard({ handover }: { handover: Handover }) {
  return (
    <Card className="mt-4 p-5">
      <h2 className="text-lg font-semibold">Handed over to the deck orchestrator</h2>
      <p className="mt-2 text-sm">
        Pick this job in the orchestrator to build MAP Assess and CVA decks from these results: <code>{handover.job_id}</code>
      </p>
      {handover.files?.length ? <p className="mt-1 text-sm text-[var(--color-gray-500)]">Sent: {handover.files.map((file) => file.filename).join(', ')}</p> : null}
    </Card>
  );
}
