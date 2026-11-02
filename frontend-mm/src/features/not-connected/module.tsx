import { LayoutDashboard } from 'lucide-react';

import { agentById } from '@/features/agents/registry';
import type { AgentId, AgentModule } from '@/features/agents/types';
import { Notice } from '@/shared/components/notice';
import { PageHeader } from '@/shared/components/page-header';

const PAGE = 'overview';

/**
 * The stand-in for an agent whose screens are not part of the dashboard yet. It only says so: it has no data, no buttons and calls no API, so
 * the sidebar, Switch agent and sign-in can be used and checked before any agent's own screens arrive.
 */
export function notConnectedModule(id: AgentId): AgentModule {
  const name = agentById(id)?.name ?? 'This agent';
  return {
    id,
    subtitle: 'Not connected yet',
    defaultPage: PAGE,
    nav: [{ items: [{ id: PAGE, label: 'Overview', icon: LayoutDashboard }] }],
    Screen: () => (
      <>
        <PageHeader eyebrow={name} title="Overview" description={agentById(id)?.tagline} />
        <Notice title={`${name} is not connected yet`}>
          <p>Its screens appear here once the agent team shares its working version. Until then there is nothing to run on this page.</p>
        </Notice>
      </>
    ),
    titleOf: () => 'Overview',
  };
}
