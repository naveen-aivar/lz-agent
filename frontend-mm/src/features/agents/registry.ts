import { Calculator, ClipboardCheck, DraftingCompass, FileOutput, PlaneLanding, Presentation, Rocket, Split, type LucideIcon } from 'lucide-react';

import type { AgentId, AgentModule } from '@/features/agents/types';

export type { AgentId } from '@/features/agents/types';

export interface AgentEntry {
  id: AgentId;
  /** The name on the switcher, in the sidebar and in the browser tab. */
  name: string;
  /** One plain sentence: what the agent is for. */
  tagline: string;
  icon: LucideIcon;
  /** Loads the agent's screens (its own chunk: nothing of an agent is downloaded until it is opened). */
  load: () => Promise<AgentModule>;
  /** Its screens are in the dashboard and can be opened. False shows it under "Upcoming" in Switch agent, unselectable. */
  connected: boolean;
}

/** An agent whose screens have not been brought in yet: it opens a page that says so and calls nothing. */
const notConnected = (id: AgentId) => () => import('@/features/not-connected/module').then((m) => m.notConnectedModule(id));

/**
 * The Migration and Modernization agents the dashboard hosts, in the order a migration meets them.
 * An agent's screens are added by giving it a module (src/features/<id>/module.tsx) and pointing its `load` here at that module.
 */
export const AGENTS: readonly AgentEntry[] = [
  {
    id: 'cva-output',
    name: 'CVA Output Processing Agent',
    tagline: 'Turns a discovery file into costs, findings and a package to review.',
    icon: FileOutput,
    load: () => import('@/features/cva-output/module').then((mod) => mod.default),
    connected: true,
  },
  {
    id: 'seven-rs',
    name: '7Rs Agent',
    tagline: 'Suggests one of the 7 Rs (rehost, replatform, refactor and the rest) for each workload.',
    icon: Split,
    load: notConnected('seven-rs'),
    connected: false,
  },
  {
    id: 'mra',
    name: 'MRA Agent',
    tagline: 'Scores how ready a customer is to migrate, then prepares the readout.',
    icon: ClipboardCheck,
    load: () => import('@/features/mra/module').then((mod) => mod.default),
    connected: true,
  },
  {
    id: 'architecture-design',
    name: 'Architecture Design Agent',
    tagline: 'Drafts the target AWS architecture for the workloads.',
    icon: DraftingCompass,
    load: () => import('@/features/architecture-design/module').then((mod) => mod.default),
    connected: true,
  },
  {
    id: 'tco',
    name: 'TCO Agent',
    tagline: 'Compares what the workloads cost today with what they would cost on AWS.',
    icon: Calculator,
    load: () => import('@/features/tco/module').then((mod) => mod.default),
    connected: true,
  },
  {
    id: 'orchestrator',
    name: 'Deck Orchestrator',
    tagline: 'Builds the final MAP Assess and CVA decks from the other agents’ results.',
    icon: Presentation,
    load: () => import('@/features/orchestrator/module').then((mod) => mod.default),
    connected: true,
  },
  {
    id: 'landing-zone',
    name: 'Landing Zone Deployment Agent',
    tagline: 'Prepares and deploys the customer’s AWS landing zone.',
    icon: PlaneLanding,
    load: notConnected('landing-zone'),
    connected: false,
  },
  {
    id: 'migration-launch',
    name: 'Migration Launch Agent',
    tagline: 'Plans the migration waves and starts them.',
    icon: Rocket,
    load: notConnected('migration-launch'),
    connected: false,
  },
];

// The first connected agent, so a first-time visitor lands on a working page rather than "not connected yet".
// Falls back to the very first entry if, one day, none are connected yet.
export const DEFAULT_AGENT_ID: AgentId = (AGENTS.find((agent) => agent.connected) ?? AGENTS[0]).id;

export function agentById(id: string | null | undefined): AgentEntry | undefined {
  return AGENTS.find((agent) => agent.id === id);
}
