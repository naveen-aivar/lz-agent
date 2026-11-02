'use client';

import { Check } from 'lucide-react';

import { MRA_STAGES, type MraRun, type MraStage } from '@/features/mra/types';

function counts(run: MraRun): Partial<Record<MraStage, number>> {
  return {
    ratings: run.blank_ratings?.length ?? 0,
    activities: (run.activities ?? []).filter((item) => item.decision === 'pending' && item.needs_action).length,
    validation: (run.validation ?? []).filter((item) => item.resolution === 'open' && item.kind !== 'blank_rating').length,
    proposals: (run.proposals ?? []).filter((item) => item.status === 'proposed').length,
    release: run.status?.blockers?.length ?? 0,
  };
}

/** The review, as steps. Finished steps can be opened. The current one pulses, unless the page is already showing the scoring dial. */
export function ReviewStepper({
  stage,
  run,
  busy,
  onPick,
}: {
  stage: MraStage;
  run: MraRun;
  busy: boolean;
  onPick: (stage: MraStage) => void;
}) {
  const open = counts(run);
  const index = MRA_STAGES.findIndex((item) => item.id === stage);
  return (
    <ol className="mb-6 flex flex-wrap gap-2" aria-label="Review steps">
      {MRA_STAGES.map((item, position) => {
        const state = position < index ? 'done' : position === index ? 'current' : 'later';
        const count = open[item.id];
        return (
          <li key={item.id}>
            <button
              type="button"
              aria-current={state === 'current' ? 'step' : undefined}
              className="flex items-center gap-2 rounded-full px-1 py-1 text-sm"
              onClick={() => onPick(item.id)}
            >
              <span
                className={`grid h-6 w-6 place-items-center rounded-full border text-xs ${
                  state === 'done'
                    ? 'border-[var(--color-success-700)] bg-[var(--color-success-50)] text-[var(--color-success-700)]'
                    : state === 'current'
                      ? `border-[var(--color-primary-600)] text-[var(--color-primary-700)] ${busy ? '' : 'mra-step-current'}`
                      : 'border-[var(--color-gray-200)] text-[var(--color-gray-500)]'
                }`}
              >
                {state === 'done' ? <Check className="animate-tick-in h-3.5 w-3.5" aria-hidden /> : position + 1}
              </span>
              <span className={state === 'later' ? 'text-[var(--color-gray-500)]' : 'font-medium text-[var(--color-gray-900)]'}>{item.label}</span>
              {count ? <span className="rounded-full bg-[var(--color-warning-50)] px-1.5 text-xs text-[var(--color-warning-700)]">{count}</span> : null}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
