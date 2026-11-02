'use client';

import { PERSON_STEPS, personStep } from '@/features/tco/format';

/** The five things a person does. Finished steps can be looked at; the current one shows a single quiet pulse while work is running. */
export function AssessmentStepper({ status }: { status: string }) {
  const current = personStep(status);
  if (current < 0) return null;
  const done = status === 'COMPLETED';
  return (
    <ol className="mb-6 flex flex-wrap gap-2" aria-label="Progress">
      {PERSON_STEPS.map((step, index) => {
        const state = done || index < current ? 'done' : index === current ? 'current' : 'later';
        return (
          <li key={step.id} aria-current={state === 'current' ? 'step' : undefined} className="flex items-center gap-2 text-sm">
            <span
              className={`grid h-6 w-6 place-items-center rounded-full border text-xs ${
                state === 'done'
                  ? 'border-[var(--color-success-700)] bg-[var(--color-success-50)] text-[var(--color-success-700)]'
                  : state === 'current'
                    ? 'tco-current border-[var(--color-primary-600)] text-[var(--color-primary-700)]'
                    : 'border-[var(--color-gray-200)] text-[var(--color-gray-500)]'
              }`}
            >
              {state === 'done' ? <span className="animate-tick-in">✓</span> : index + 1}
            </span>
            <span className={state === 'later' ? 'text-[var(--color-gray-500)]' : 'font-medium text-[var(--color-gray-900)]'}>{step.label}</span>
            {index < PERSON_STEPS.length - 1 ? <span aria-hidden className="mx-1 hidden h-px w-6 bg-[var(--color-gray-200)] sm:block" /> : null}
          </li>
        );
      })}
    </ol>
  );
}
