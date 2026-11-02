'use client';

import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';

import type { AgentEntry, AgentId } from '@/features/agents/registry';
import type { AgentModule, AgentRoute, Navigate, NavItem } from '@/features/agents/types';
import { SwitchAgent } from '@/features/shell/switch-agent';
import { useSidebarCollapsed } from '@/features/shell/sidebar-state';
import { AccountCard } from '@/shared/auth/account-card';
import { AivarLogo } from '@/shared/components/aivar-logo';
import { IngramLogo } from '@/shared/components/ingram-logo';
import { Skeleton } from '@/shared/design-system/ui/skeleton';
import { cn } from '@/shared/utils/cn';

/** Active item: brand gradient pill, matching ingrammicro.com primary buttons. */
const ACTIVE_ITEM = 'bg-[image:var(--gradient-primary)] font-semibold !text-white shadow-[0_6px_16px_-6px_rgba(21,112,239,0.6)]';
const ICON_BUTTON =
  'inline-flex cursor-pointer items-center justify-center rounded-xl text-[var(--color-gray-500)] hover:bg-[var(--color-primary-50)] hover:text-[var(--color-primary-700)]';

const noBadges = (): Record<string, string | number | null | undefined> => ({});

/**
 * The dashboard's one sidebar, the same for every agent: the logo, the open agent's name, the agent's own navigation, then at the foot "Switch agent"
 * and the signed-in person. While an agent is still opening (`module` is null) everything already known stays real and is switched off; only the
 * navigation labels are skeletons.
 */
export function Sidebar({
  agent,
  module,
  route,
  navigate,
  onSelectAgent,
  failed = false,
}: {
  agent: AgentEntry;
  module: AgentModule | null;
  route: AgentRoute | null;
  navigate: Navigate;
  onSelectAgent: (id: AgentId) => void;
  failed?: boolean;
}) {
  const [collapsed, setCollapsed] = useSidebarCollapsed();
  const ready = module !== null && route !== null;
  const Extra = module?.SidebarExtra;

  return (
    <aside
      data-app-sidebar=""
      className={cn(
        'flex h-full shrink-0 flex-col overflow-hidden rounded-[28px] border border-[var(--color-gray-100)] bg-[var(--color-sidebar)] text-[var(--color-gray-700)] shadow-[var(--shadow-md)] backdrop-blur-xl transition-[width] duration-300 ease-out motion-reduce:transition-none',
        collapsed ? 'w-[4.5rem]' : 'w-72',
      )}
    >
      {/* The logo's clear space (the logo brings its own) is the header's padding, so nothing else sits in it. */}
      <div className={cn('flex items-center gap-2', collapsed ? 'justify-center px-2 pt-5 pb-3' : 'pr-4')}>
        {collapsed ? null : (
          <div className="min-w-0 flex-1" aria-label="Ingram Micro">
            <IngramLogo size="sm" />
          </div>
        )}
        <button type="button" onClick={() => setCollapsed(!collapsed)} aria-expanded={!collapsed} aria-controls="msp-nav" className={cn(ICON_BUTTON, 'h-9 w-9 shrink-0')}>
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          <span className="sr-only">{collapsed ? 'Expand sidebar' : 'Collapse sidebar'}</span>
        </button>
      </div>

      {collapsed ? null : (
        <div className="px-6 pt-1 pb-3">
          <p className="text-sm leading-5 font-semibold text-[var(--color-gray-900)]">{agent.name}</p>
          {module ? (
            module.subtitle ? <p className="text-xs leading-4 text-[var(--color-gray-500)]">{module.subtitle}</p> : null
          ) : (
            <Skeleton className="mt-1.5 h-3 w-28" />
          )}
        </div>
      )}

      {Extra && route ? <Extra collapsed={collapsed} navigate={navigate} /> : null}

      <nav id="msp-nav" aria-label="Main" className="flex-1 overflow-x-hidden overflow-y-auto pt-1 pb-4">
        {module && route ? <ModuleNav key={module.id} module={module} route={route} navigate={navigate} collapsed={collapsed} /> : <NavSkeleton collapsed={collapsed} />}
      </nav>

      <div className={cn('shrink-0 px-3 pb-2', collapsed && 'px-2')}>
        <SwitchAgent active={agent} onSelect={onSelectAgent} collapsed={collapsed} disabled={!ready && !failed} />
      </div>
      {/* The signed-in person with Sign out, at the foot of the sidebar (nothing is drawn without sign-in). */}
      <AccountCard collapsed={collapsed} disabled={!ready} />

      <footer className={cn('min-h-[var(--chrome-footer-height)] shrink-0 border-t border-[var(--color-gray-100)] px-6 py-4 text-xs text-[var(--color-gray-500)]', collapsed && 'px-2 text-center')}>
        {collapsed ? null : (
          <div>
            <p>Powered by</p>
            <AivarLogo className="mt-1.5 h-5 w-auto text-[var(--color-gray-900)]" />
          </div>
        )}
      </footer>
    </aside>
  );
}

function ModuleNav({ module, route, navigate, collapsed }: { module: AgentModule; route: AgentRoute; navigate: Navigate; collapsed: boolean }) {
  const useBadges = module.useNavBadges ?? noBadges;
  const badges = useBadges();
  const active = module.activeNav?.(route) ?? route.page;
  return (
    <>
      {module.nav.map((section, index) => (
        <div key={section.label ?? index} role="group" aria-label={section.label} className={cn(index > 0 && 'mt-4')}>
          {collapsed ? (
            index > 0 ? <hr className="mx-3 mb-3 border-[var(--color-gray-100)]" /> : null
          ) : section.label ? (
            <p aria-hidden className="px-6 pb-2 text-xs font-semibold tracking-wide text-[var(--color-gray-500)] uppercase">
              {section.label}
            </p>
          ) : null}
          <div className={cn('space-y-1 px-3', collapsed && 'px-2')}>
            {section.items.map((item) => (
              <NavButton key={item.id} item={item} badge={badges[item.id] ?? item.badge} collapsed={collapsed} active={item.id === active} onSelect={() => navigate(item.id)} />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

function NavButton({ item, badge, collapsed, active, onSelect }: { item: NavItem; badge?: string | number | null; collapsed: boolean; active: boolean; onSelect: () => void }) {
  const Icon = item.icon;
  const hasBadge = badge !== undefined && badge !== null && badge !== '' && badge !== 0;
  return (
    <button
      type="button"
      onClick={onSelect}
      title={collapsed ? item.label : undefined}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex w-full cursor-pointer items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm leading-5 font-medium transition-colors',
        collapsed && 'justify-center px-0',
        active ? ACTIVE_ITEM : 'hover:bg-[var(--color-primary-50)] hover:text-[var(--color-primary-700)]',
      )}
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      <span className={cn('min-w-0 flex-1 truncate', collapsed && 'sr-only')}>{item.label}</span>
      {hasBadge && !collapsed ? (
        <span className={cn('ml-auto shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold', active ? 'bg-white/25 text-white' : 'bg-[var(--color-warning-50)] text-[var(--color-warning-700)]')}>{badge}</span>
      ) : null}
    </button>
  );
}

/** The navigation while the agent's screens load: a skeleton for each label, nothing else. */
function NavSkeleton({ collapsed }: { collapsed: boolean }) {
  return (
    <div role="status" aria-label="Loading the navigation" className={cn('space-y-1 px-3', collapsed && 'px-2')}>
      {[0, 1, 2, 3].map((row) => (
        <Skeleton key={row} className={cn('h-10 rounded-xl', collapsed ? 'mx-auto w-10' : 'w-full')} />
      ))}
    </div>
  );
}
