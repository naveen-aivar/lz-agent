'use client';

import * as Popover from '@radix-ui/react-popover';
import { Check, ChevronsUpDown, Repeat } from 'lucide-react';
import { useState } from 'react';

import { AGENTS, type AgentEntry, type AgentId } from '@/features/agents/registry';
import { cn } from '@/shared/utils/cn';

/**
 * "Switch agent", in the sidebar just above the person's avatar. It opens the list of agents; choosing one changes the whole dashboard to that agent
 * (the sidebar's navigation, the page, the agent's own API). While an agent is still opening it is switched off. In a collapsed sidebar it is just the icon.
 */
export function SwitchAgent({
  active,
  onSelect,
  collapsed = false,
  disabled = false,
}: {
  active: AgentEntry;
  onSelect: (id: AgentId) => void;
  collapsed?: boolean;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const available = AGENTS.filter((agent) => agent.connected);
  const upcoming = AGENTS.filter((agent) => !agent.connected);
  return (
    <Popover.Root open={open && !disabled} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={`Switch agent ${active.name}`}
          className={cn(
            'flex cursor-pointer items-center gap-2.5 rounded-[14px] border border-[var(--color-gray-100)] bg-[var(--color-surface)] text-left shadow-[var(--shadow-sm)] transition-colors',
            'hover:border-[var(--color-primary-200)] hover:bg-[var(--color-primary-25)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary-600)]',
            'disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-[var(--color-gray-100)] disabled:hover:bg-[var(--color-surface)]',
            collapsed ? 'mx-auto w-auto justify-center p-2' : 'w-full px-3 py-2.5',
          )}
        >
          <span aria-hidden className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-[var(--color-primary-50)] text-[var(--color-primary-700)]">
            <Repeat className="h-5 w-5" />
          </span>
          {collapsed ? null : (
            <>
              <span aria-hidden className="flex min-w-0 flex-1 flex-col leading-tight">
                <span className="text-sm font-semibold text-[var(--color-gray-900)]">Switch agent</span>{' '}
                {/* The space is for a checker that reads the visible text: it must equal the button's label ("Switch agent <name>"). */}
                <span className="truncate text-xs text-[var(--color-gray-700)]">{active.name}</span>
              </span>
              <ChevronsUpDown className="h-4 w-4 shrink-0 text-[var(--color-gray-500)]" aria-hidden />
            </>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="right"
          align="end"
          sideOffset={12}
          collisionPadding={12}
          aria-label="Switch agent"
          className="animate-fade-in z-50 w-[min(22rem,calc(100vw-7rem))] rounded-[var(--radius-lg)] border border-[var(--color-gray-100)] bg-[var(--color-surface)] p-2 shadow-[var(--shadow-lg)] outline-none"
        >
          <p className="px-3 pt-2 pb-1 text-sm font-semibold text-[var(--color-gray-900)]">Switch agent</p>
          <ul className="flex flex-col gap-0.5">
            {available.map((agent) => (
              <AgentRow key={agent.id} agent={agent} current={agent.id === active.id} onSelect={() => { setOpen(false); if (agent.id !== active.id) onSelect(agent.id); }} />
            ))}
          </ul>
          {upcoming.length ? (
            <>
              <p className="mt-2 border-t border-[var(--color-gray-100)] px-3 pt-2 pb-1 text-xs font-semibold tracking-wide text-[var(--color-gray-500)] uppercase">Upcoming</p>
              <ul className="flex flex-col gap-0.5">
                {upcoming.map((agent) => (
                  <AgentRow key={agent.id} agent={agent} current={false} upcoming />
                ))}
              </ul>
            </>
          ) : null}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** One row of the switcher: a selectable agent, or (`upcoming`) one whose screens are not in the dashboard yet, shown but not selectable. */
function AgentRow({ agent, current, upcoming = false, onSelect }: { agent: AgentEntry; current: boolean; upcoming?: boolean; onSelect?: () => void }) {
  const Icon = agent.icon;
  return (
    <li className="flex items-stretch gap-1">
      <button
        type="button"
        aria-current={current ? 'true' : undefined}
        disabled={upcoming}
        onClick={onSelect}
        className={cn(
          'flex min-w-0 flex-1 items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--color-primary-600)]',
          upcoming ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
          current ? 'bg-[var(--color-primary-50)]' : !upcoming && 'hover:bg-[var(--color-gray-50)]',
        )}
      >
        <span aria-hidden className={cn('mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', upcoming ? 'bg-[var(--color-gray-100)] text-[var(--color-gray-500)]' : 'bg-[var(--color-primary-50)] text-[var(--color-primary-700)]')}>
          <Icon className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 text-sm font-semibold text-[var(--color-gray-900)]">
            {agent.name}
            {current ? <Check className="h-4 w-4 text-[var(--color-primary-700)]" aria-label="Open now" /> : null}
            {upcoming ? <span className="rounded-full bg-[var(--color-gray-100)] px-2 py-0.5 text-[10px] font-semibold tracking-wide text-[var(--color-gray-500)] uppercase">Coming soon</span> : null}
          </span>
          <span className={cn('mt-0.5 block text-xs leading-4', current ? 'text-[var(--color-gray-700)]' : 'text-[var(--color-gray-500)]')}>{agent.tagline}</span>
        </span>
      </button>
    </li>
  );
}
