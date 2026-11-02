'use client';

import { LayoutList, Plus } from 'lucide-react';

import type { AgentModule, AgentRoute } from '@/features/agents/types';
import { AssessmentDetail, AssessmentList, NewAssessment } from '@/features/tco/screens';
import './tco.css';

function Screen({ route, navigate }: { route: AgentRoute; navigate: (page: string, params?: Record<string, string>) => void }) {
  return (
    <div className="mm-tco">
      {route.page === 'new' ? <NewAssessment navigate={navigate} /> : null}
      {route.page === 'job' && route.params.id ? <AssessmentDetail id={route.params.id} /> : null}
      {route.page === 'assessments' || (route.page === 'job' && !route.params.id) ? <AssessmentList navigate={navigate} /> : null}
    </div>
  );
}

function titleOf(route: AgentRoute): string {
  if (route.page === 'new') return 'New assessment';
  if (route.page === 'job') return 'Assessment';
  return 'Assessments';
}

const agentModule: AgentModule = {
  id: 'tco',
  subtitle: 'Compares today’s cost with AWS.',
  defaultPage: 'assessments',
  nav: [
    {
      items: [
        { id: 'assessments', label: 'Assessments', icon: LayoutList },
        { id: 'new', label: 'New assessment', icon: Plus },
      ],
    },
  ],
  Screen,
  titleOf,
  activeNav: (route) => (route.page === 'job' ? 'assessments' : route.page),
};

export default agentModule;
