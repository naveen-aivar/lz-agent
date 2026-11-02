'use client';

import { useEffect } from 'react';
import { toast } from 'sonner';

import type { AgentEntry } from '@/features/agents/registry';
import { useSelectedAgent } from '@/features/agents/use-selected-agent';
import type { AgentModule } from '@/features/agents/types';
import { AgentRouteProvider, useAgentRoute } from '@/features/shell/route-context';
import { ScreenBoundary } from '@/features/shell/screen-boundary';
import { Sidebar } from '@/features/shell/sidebar';
import { Topbar } from '@/features/shell/topbar';
import { TopbarSlotProvider } from '@/features/shell/topbar-slot';
import { useAgentModule } from '@/features/shell/use-agent-module';
import { BrandBackdrop } from '@/shared/components/brand-backdrop';
import { Notice } from '@/shared/components/notice';
import { Button } from '@/shared/design-system/ui/button';
import { Skeleton } from '@/shared/design-system/ui/skeleton';
import { ToasterProvider } from '@/shared/design-system/ui/toaster';

/**
 * The signed-in dashboard: one sidebar and one top bar for every agent, and the open agent's page in the middle. The address never changes; choosing
 * an agent in "Switch agent" swaps what is inside, and an agent that has not been opened yet is fetched first (its own chunk) while the sidebar
 * shows everything it already knows, switched off, with only the navigation and the page as skeletons.
 */
export function Dashboard() {
  const { agent, select } = useSelectedAgent();
  const { module, failed, retry } = useAgentModule(agent);

  useEffect(() => {
    if (!agent) document.title = 'Migration and Modernization Agents | Ingram Micro';
  }, [agent]);

  // A message belongs to the agent that raised it: when the person switches agent it goes away with it (a red "could not load" from one agent
  // must not sit over the next one's page).
  const agentId = agent?.id;
  useEffect(() => {
    toast.dismiss();
  }, [agentId]);

  return (
    <ToasterProvider>
      <div className="relative isolate flex h-dvh gap-3 overflow-clip bg-[var(--color-gray-25)] p-3">
        <BrandBackdrop />
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-[var(--radius-pill)] focus:bg-[var(--color-surface)] focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-[var(--color-primary-700)] focus:shadow-[var(--shadow-md)]"
        >
          Skip to content
        </a>
        {agent ? null : (
          <main>
            <h1 className="sr-only">Migration and Modernization Agents</h1>
          </main>
        )}
        {agent ? (
          <TopbarSlotProvider>
            {module ? (
              <AgentRouteProvider key={agent.id} agentId={agent.id} defaultPage={module.defaultPage}>
                <WithProvider module={module}>
                  <Workspace agent={agent} module={module} onSelectAgent={select} />
                </WithProvider>
              </AgentRouteProvider>
            ) : (
              <Opening agent={agent} failed={failed} retry={retry} onSelectAgent={select} />
            )}
          </TopbarSlotProvider>
        ) : null}
      </div>
    </ToasterProvider>
  );
}

function WithProvider({ module, children }: { module: AgentModule; children: React.ReactNode }) {
  const Provider = module.Provider;
  return Provider ? <Provider>{children}</Provider> : <>{children}</>;
}

/** The agent is ready: its sidebar, its top bar and its page. */
function Workspace({ agent, module, onSelectAgent }: { agent: AgentEntry; module: AgentModule; onSelectAgent: (id: AgentEntry['id']) => void }) {
  const { route, navigate } = useAgentRoute();
  const title = module.titleOf(route);
  useEffect(() => {
    document.title = `${title} | ${agent.name} | Ingram Micro`;
  }, [title, agent.name]);
  const Screen = module.Screen;
  return (
    <>
      <Sidebar agent={agent} module={module} route={route} navigate={navigate} onSelectAgent={onSelectAgent} />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-clip">
        <Topbar agent={agent} title={title} onHome={() => navigate(module.defaultPage)} />
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-4 pb-8">
          <main id="main-content" tabIndex={-1} className={module.fullWidth ? 'outline-none' : 'mx-auto w-full max-w-[var(--content-max-width)] outline-none'}>
            <ScreenBoundary resetKey={`${route.page}:${JSON.stringify(route.params)}`}>
              <div key={route.page} className="view-enter flex flex-col gap-6">
                <Screen route={route} navigate={navigate} />
              </div>
            </ScreenBoundary>
          </main>
        </div>
      </div>
    </>
  );
}

/** The agent's screens are still being fetched (or could not be): the sidebar as it will be, with the navigation and the page as skeletons. */
function Opening({ agent, failed, retry, onSelectAgent }: { agent: AgentEntry; failed: boolean; retry: () => void; onSelectAgent: (id: AgentEntry['id']) => void }) {
  return (
    <>
      <Sidebar agent={agent} module={null} route={null} navigate={() => {}} onSelectAgent={onSelectAgent} failed={failed} />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-clip">
        <Topbar agent={agent} title={null} onHome={() => {}} />
        <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-4 pb-8">
          {failed ? (
            <Notice tone="danger" title={`We could not open ${agent.name}`}>
              <p>Check your connection and try again.</p>
              <Button type="button" variant="secondary" size="sm" className="mt-3" onClick={retry}>
                Try again
              </Button>
            </Notice>
          ) : (
            <div role="status" aria-label={`Opening ${agent.name}`} className="flex flex-col gap-4">
              <Skeleton className="h-9 w-1/3" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="mt-2 h-40 w-full rounded-[var(--radius-lg)]" />
              <Skeleton className="h-64 w-full rounded-[var(--radius-lg)]" />
            </div>
          )}
        </div>
      </div>
    </>
  );
}
