'use client';

import { FilePlus2, LayoutList } from 'lucide-react';

import type { AgentModule, AgentRoute } from '@/features/agents/types';
import { RunScreen } from '@/features/cva-output/run';
import { NewRunScreen, RunsScreen } from '@/features/cva-output/runs';
import { CVA_STAGES } from '@/features/cva-output/types';
import './cva.css';

function Screen({ route, navigate }: { route: AgentRoute; navigate: (page: string, params?: Record<string, string>) => void }) {
  return (
    <div className="mm-cva-output">
      {route.page === 'new' ? <NewRunScreen navigate={navigate} /> : null}
      {route.page === 'run' && route.params.id ? <RunScreen id={route.params.id} stage={route.params.stage || 'overview'} navigate={navigate} /> : null}
      {route.page === 'runs' || (route.page === 'run' && !route.params.id) ? <RunsScreen navigate={navigate} /> : null}
    </div>
  );
}

function titleOf(route: AgentRoute): string {
  if (route.page === 'new') return 'New run';
  if (route.page === 'run') return CVA_STAGES.find((item) => item.id === route.params.stage)?.label ?? 'Run';
  return 'Runs';
}

const agentModule: AgentModule = {
  id: 'cva-output',
  subtitle: 'Turns a discovery file into a package to review.',
  defaultPage: 'runs',
  nav: [{ items: [{ id: 'runs', label: 'Runs', icon: LayoutList }, { id: 'new', label: 'New run', icon: FilePlus2 }] }],
  Screen,
  titleOf,
  activeNav: (route) => (route.page === 'run' ? 'runs' : route.page),
};

export default agentModule;
