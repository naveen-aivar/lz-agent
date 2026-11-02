/** Dialogs and lists are drawn outside the page, so they need their own copy of the scope class or the agent's styles miss them. */
export const PORTAL_ID = 'mm-architecture-design-portal';

export function portalContainer() {
  if (typeof document === 'undefined') return undefined;
  return document.getElementById(PORTAL_ID) ?? undefined;
}
