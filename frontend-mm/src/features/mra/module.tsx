'use client';

import { FilePlus2, LayoutList, Settings } from 'lucide-react';

import type { AgentModule, AgentRoute } from '@/features/agents/types';
import { NewRunScreen, RunsScreen } from '@/features/mra/runs';
import { RunScreen } from '@/features/mra/run';
import { SettingsScreen } from '@/features/mra/settings';
import { MRA_STAGES } from '@/features/mra/types';
import './mra.css';

function Screen({ route, navigate }: { route: AgentRoute; navigate: (page: string, params?: Record<string, string>) => void }) {
  return (
    <div className="mm-mra">
      {route.page === 'new' ? <NewRunScreen navigate={navigate} /> : null}
      {route.page === 'settings' ? <SettingsScreen /> : null}
      {route.page === 'run' && route.params.id ? <RunScreen id={route.params.id} stage={route.params.stage || 'overview'} navigate={navigate} /> : null}
      {route.page === 'runs' || (route.page === 'run' && !route.params.id) ? <RunsScreen navigate={navigate} /> : null}
    </div>
  );
}

function titleOf(route: AgentRoute): string {
  if (route.page === 'new') return 'New assessment';
  if (route.page === 'settings') return 'Settings';
  if (route.page === 'run') return MRA_STAGES.find((item) => item.id === route.params.stage)?.label ?? 'Run';
  return 'Runs';
}

const agentModule: AgentModule = {
  id: 'mra',
  subtitle: 'Scores how ready a customer is to migrate.',
  defaultPage: 'runs',
  nav: [
    {
      items: [
        { id: 'runs', label: 'Runs', icon: LayoutList },
        { id: 'new', label: 'New assessment', icon: FilePlus2 },
        { id: 'settings', label: 'Settings', icon: Settings },
      ],
    },
  ],
  Screen,
  titleOf,
  activeNav: (route) => (route.page === 'run' ? 'runs' : route.page),
};

export default agentModule;
