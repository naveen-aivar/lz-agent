'use client';

import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react';
import { FilePlus2, LayoutList, RefreshCw } from 'lucide-react';

import { bindNavigate, followLink } from '@/features/architecture-design/adapters/route';
import { PORTAL_ID } from '@/features/architecture-design/adapters/portal';
import { api } from '@/features/architecture-design/app/api.js';
import { ACTIVE } from '@/features/architecture-design/app/format.js';
import NewArchitecture from '@/features/architecture-design/app/pages/NewArchitecture.jsx';
import Runs from '@/features/architecture-design/app/pages/Runs.jsx';
import { usePoll } from '@/features/architecture-design/app/usePoll.js';
import '@/features/architecture-design/app/architecture.css';
import '@/features/architecture-design/header-actions.css';
import '@/features/architecture-design/landing-scene.css';
import '@/features/architecture-design/skeletons.css';

import type { AgentModule, AgentRoute } from '@/features/agents/types';
import { TopbarActions } from '@/features/shell/topbar-slot';
import { Button } from '@/shared/design-system/ui/button';

type RunRow = { status?: string; title?: string; run_id?: string };
type Session = { user_runs_today?: number; runs_per_user_day?: number; runs_today?: number; runs_per_day?: number };

function quotaText(session: Session | null): string | null {
  if (session && typeof session.user_runs_today === 'number' && (session.runs_per_user_day ?? 0) < 1e6) {
    return `${session.user_runs_today} / ${session.runs_per_user_day} runs today`;
  }
  if (session && typeof session.runs_today === 'number') {
    return (session.runs_per_day ?? 0) >= 1e6 ? `${session.runs_today} runs today` : `${session.runs_today} / ${session.runs_per_day} runs today`;
  }
  return null;
}

type Poll<T> = { data: T | null; error: string | null; refresh: () => void };

// The run list and the session poll, shared with the sidebar's badge and the screen below. A plain module-level
// object will not do here: the dashboard passes this agent's screens down through a `children` prop that does not
// change identity on every poll tick, so React skips re-rendering that subtree and the screen never sees the new
// data. Context is the one mechanism React re-checks regardless of that: every consumer below gets the fresh value.
const ArchContext = createContext<{ runs: Poll<RunRow[]>; session: Poll<Session> } | null>(null);
const emptyPoll = { data: null, error: null, refresh: () => {} };

function Provider({ children }: { children: ReactNode }) {
  const runs = usePoll(api.runs, { ms: 15000 }) as Poll<RunRow[]>;
  const session = usePoll(api.session, { ms: 60000 }) as Poll<Session>;
  const value = useMemo(() => ({ runs, session }), [runs, session]);
  // The scope class stays on the screen and the portal, not around the sidebar. The agent's stylesheet
  // resets every button and paints a full-page background; wrapping the shell in it hid the dashboard.
  return (
    <ArchContext.Provider value={value}>
      {children}
      <div id={PORTAL_ID} className="mm-architecture-design" />
    </ArchContext.Provider>
  );
}

function useNavBadges() {
  const runs = useContext(ArchContext)?.runs.data;
  const rows = Array.isArray(runs) ? runs : [];
  const running = rows.filter((run) => run.status != null && ACTIVE.has(run.status)).length;
  return { runs: running || null };
}

function Screen({ route, navigate }: { route: AgentRoute; navigate: (page: string, params?: Record<string, string>) => void }) {
  useEffect(() => {
    bindNavigate(navigate);
  }, [navigate]);
  const context = useContext(ArchContext);
  const runs = context?.runs ?? emptyPoll;
  if (Array.isArray(runs.data)) lastRuns = runs.data;
  const quota = quotaText(context?.session.data ?? null);
  return (
    <div id="content" className="mm-architecture-design" onClick={followLink}>
      <TopbarActions>
        {quota ? <span className="text-sm text-[var(--color-gray-500)]">{quota}</span> : null}
        <Button variant="secondary" size="sm" onClick={() => window.dispatchEvent(new Event('app:refresh'))}>
          <RefreshCw size={16} aria-hidden /> Refresh
        </Button>
      </TopbarActions>
      {route.page === 'new' ? <NewArchitecture /> : <Runs id={route.params.id} runs={runs} />}
    </div>
  );
}

// titleOf has no React tree of its own to read context from: the dashboard calls it directly for the top bar and
// the browser tab, outside any component. It keeps the last list the screen itself last rendered with.
let lastRuns: RunRow[] = [];

function titleOf(route: AgentRoute): string {
  if (route.page === 'new') return 'New architecture';
  if (route.params.id) {
    const run = lastRuns.find((item) => item.run_id === route.params.id);
    return run?.title || 'Run';
  }
  return 'Runs';
}

const agentModule: AgentModule = {
  id: 'architecture-design',
  subtitle: 'Design only. It never deploys.',
  defaultPage: 'runs',
  nav: [
    {
      items: [
        { id: 'runs', label: 'Runs', icon: LayoutList },
        { id: 'new', label: 'New architecture', icon: FilePlus2 },
      ],
    },
  ],
  Provider,
  useNavBadges,
  Screen,
  titleOf,
  activeNav: (route) => (route.page === 'new' ? 'new' : 'runs'),
};

export default agentModule;
