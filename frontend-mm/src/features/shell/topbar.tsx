'use client';

import { ChevronRight } from 'lucide-react';

import type { AgentEntry } from '@/features/agents/registry';
import { TopbarSlotTarget } from '@/features/shell/topbar-slot';
import { Skeleton } from '@/shared/design-system/ui/skeleton';

/** Ingram Micro Agents > the agent > the page, and at the right whatever the page puts there (see TopbarActions). */
export function Topbar({ agent, title, onHome }: { agent: AgentEntry; title: string | null; onHome: () => void }) {
  const sep = <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--color-gray-300)]" aria-hidden />;
  return (
    <header className="flex min-h-16 w-full shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 px-6 py-2">
      {/* The page's name for a screen reader, in the page's one banner (a second banner landmark is a fault). */}
      <h1 className="sr-only">{agent.name}</h1>
      <nav aria-label="Breadcrumb" className="min-w-0">
        <ol className="flex min-w-0 items-center gap-1.5 text-sm">
          <li className="flex min-w-0 items-center">
            <button type="button" onClick={onHome} className="cursor-pointer truncate font-semibold text-[var(--color-gray-900)] hover:text-[var(--color-primary-700)]">
              Ingram Micro Agents
            </button>
          </li>
          <li className="flex min-w-0 items-center gap-1.5">
            {sep}
            <span className="truncate font-medium text-[var(--color-gray-500)]">{agent.name}</span>
          </li>
          <li className="flex min-w-0 items-center gap-1.5">
            {sep}
            {title ? (
              <span aria-current="page" className="truncate font-medium text-[var(--color-gray-900)]">
                {title}
              </span>
            ) : (
              <Skeleton className="h-4 w-24" />
            )}
          </li>
        </ol>
      </nav>
      <TopbarSlotTarget />
    </header>
  );
}
