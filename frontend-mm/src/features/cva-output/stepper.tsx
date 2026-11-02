'use client';

import { Check } from 'lucide-react';

import { CVA_STAGES, type CvaStage } from '@/features/cva-output/types';

/** The package, as steps. The open step pulses unless the page is already showing the pages sliding into the folder. */
export function PackageStepper({ stage, busy, onPick }: { stage: CvaStage; busy: boolean; onPick: (stage: CvaStage) => void }) {
  const index = CVA_STAGES.findIndex((item) => item.id === stage);
  return (
    <ol className="mb-6 flex flex-wrap gap-2" aria-label="Package steps">
      {CVA_STAGES.map((item, position) => {
        const state = position < index ? 'done' : position === index ? 'current' : 'later';
        return (
          <li key={item.id}>
            <button type="button" aria-current={state === 'current' ? 'step' : undefined} className="flex items-center gap-2 rounded-full px-1 py-1 text-sm" onClick={() => onPick(item.id)}>
              <span className={`grid h-6 w-6 place-items-center rounded-full border text-xs ${state === 'done' ? 'border-[var(--color-success-700)] bg-[var(--color-success-50)] text-[var(--color-success-700)]' : state === 'current' ? `border-[var(--color-primary-600)] text-[var(--color-primary-700)] ${busy ? '' : 'cva-step-current'}` : 'border-[var(--color-gray-200)] text-[var(--color-gray-500)]'}`}>
                {state === 'done' ? <Check className="animate-tick-in h-3.5 w-3.5" aria-hidden /> : position + 1}
              </span>
              <span className={state === 'later' ? 'text-[var(--color-gray-500)]' : 'font-medium text-[var(--color-gray-900)]'}>{item.label}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
