import type { LucideIcon } from 'lucide-react';
import type { ComponentType, ReactNode } from 'react';

export type AgentId =
  | 'cva-output'
  | 'seven-rs'
  | 'mra'
  | 'architecture-design'
  | 'tco'
  | 'orchestrator'
  | 'landing-zone'
  | 'migration-launch';

/** One entry of the sidebar. `id` is the page it opens (the `page` of the route). */
export interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  /** A small count or word at the right of the label, e.g. the number of runs waiting for review. */
  badge?: string | number | null;
}

/** A group of sidebar entries under an optional small heading. */
export interface NavSection {
  label?: string;
  items: NavItem[];
}

/**
 * Where the open agent is: a page (a screen of that agent) and the parameters the page needs (a run id, a customer). The browser's address does
 * not change: the dashboard is one page at one address, and this lives in memory (the agent's last page is remembered while the dashboard is open).
 */
export interface AgentRoute {
  page: string;
  params: Readonly<Record<string, string>>;
}

export type Navigate = (page: string, params?: Record<string, string>) => void;

export interface ScreenProps {
  route: AgentRoute;
  navigate: Navigate;
}

/**
 * What an agent gives the dashboard. The dashboard draws everything common (the sidebar with Switch agent and the person, the top bar, the loading
 * states, sign-in); the agent gives its screens, its navigation and whatever it needs around them. An agent lives in src/features/<id>/ and exports
 * its module as the default export of src/features/<id>/module.tsx. See src/features/agents/PORTING.md.
 */
export interface AgentModule {
  id: AgentId;
  /** One short line under the agent's name in the sidebar, e.g. "Demonstration pilot". */
  subtitle?: string;
  /** The page that opens first. */
  defaultPage: string;
  /** The sidebar's navigation. */
  nav: NavSection[];
  /** Wraps everything of this agent (sidebar parts and screens): its own providers, such as a query client. */
  Provider?: ComponentType<{ children: ReactNode }>;
  /** A hook run inside Provider that returns a badge for nav items by id, e.g. () => ({ review: 17 }). */
  useNavBadges?: () => Record<string, string | number | null | undefined>;
  /** Extra sidebar content above the navigation (the WAFR customer menu). `collapsed` is true when the sidebar shows icons only. */
  SidebarExtra?: ComponentType<{ collapsed: boolean; navigate: Navigate }>;
  /** The screen for the current route. */
  Screen: ComponentType<ScreenProps>;
  /** The title of the current page, for the top bar and the browser tab. */
  titleOf: (route: AgentRoute) => string;
  /** Which sidebar entry is lit for a route, when it is not the page itself (a run's page lights "Runs"). */
  activeNav?: (route: AgentRoute) => string;
  /** The page fills the width instead of the dashboard's content width. */
  fullWidth?: boolean;
}
