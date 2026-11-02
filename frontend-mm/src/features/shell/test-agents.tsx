import { Activity, Layers, Play, Settings } from 'lucide-react';
import { vi } from 'vitest';

import type { AgentModule } from '@/features/agents/types';

/** Two made-up agents for the shell's tests, and a registry that hands them out (use with vi.mock of '@/features/agents/registry'). */
export const alphaModule: AgentModule = {
  id: 'mra',
  subtitle: 'Demonstration pilot',
  defaultPage: 'start',
  nav: [
    { label: 'Agent run', items: [{ id: 'start', label: '1. Start', icon: Play }, { id: 'review', label: '2. Review', icon: Activity }] },
    { label: 'Setup', items: [{ id: 'config', label: 'Configuration', icon: Settings }] },
  ],
  useNavBadges: () => ({ review: 17 }),
  Screen: ({ route, navigate }) => (
    <div>
      <p>Alpha page: {route.page}</p>
      <button onClick={() => navigate('config', { a: '1' })}>go to configuration</button>
    </div>
  ),
  titleOf: (route) => `Alpha ${route.page}`,
};

export const betaModule: AgentModule = {
  id: 'tco',
  defaultPage: 'portfolio',
  nav: [{ items: [{ id: 'portfolio', label: 'Portfolio', icon: Layers }] }],
  Screen: () => <p>Beta portfolio</p>,
  titleOf: () => 'Portfolio',
};

export const betaLoad = vi.fn();
export const alphaLoad = vi.fn();
export const gammaLoad = vi.fn();

export const fakeAgents = () => [
  { id: 'mra', name: 'Alpha Agent', tagline: 'Does alpha things.', icon: Play, load: alphaLoad, connected: true },
  { id: 'tco', name: 'Beta Review', tagline: 'Does beta things.', icon: Layers, load: betaLoad, connected: true },
  // Not connected yet: Switch agent must show it under "Upcoming", disabled, rather than as a normal choice.
  { id: 'architecture-design', name: 'Gamma Agent', tagline: 'Will do gamma things, one day.', icon: Settings, load: gammaLoad, connected: false },
];
