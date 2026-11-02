'use client';

import { LayoutList, Presentation } from 'lucide-react';
import type { AgentModule, AgentRoute } from '@/features/agents/types';
import { RunDetail } from '@/features/orchestrator/run-detail';
import { RunList } from '@/features/orchestrator/run-list';
import { GenerateDecks } from '@/features/orchestrator/trigger-form';

function Screen({ route, navigate }: { route: AgentRoute; navigate: (page: string, params?: Record<string, string>) => void }) {
  if (route.page === 'new') return <GenerateDecks navigate={navigate} />;
  if (route.page === 'run' && route.params.id) return <RunDetail id={route.params.id} />;
  return <RunList navigate={navigate} />;
}

function titleOf(route: AgentRoute): string {
  return route.page === 'new' ? 'Generate decks' : 'Decks';
}

const agentModule: AgentModule = {
  id: 'orchestrator',
  subtitle: 'Builds the final decks.',
  defaultPage: 'decks',
  nav: [
    {
      items: [
        { id: 'decks', label: 'Decks', icon: LayoutList },
        { id: 'new', label: 'Generate decks', icon: Presentation },
      ],
    },
  ],
  Screen,
  titleOf,
  activeNav: (route) => (route.page === 'run' ? 'decks' : route.page),
};

export default agentModule;
