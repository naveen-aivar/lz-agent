/** The shell's navigate, set while this agent is on screen. The address never changes. */
let go = () => {};

export function bindNavigate(fn) {
  go = fn;
}

/** A link the page can put in href. The screen catches the click and calls the shell. */
export function href(...parts) {
  return `#mm-arch/${parts.map((part) => encodeURIComponent(part)).join('/')}`;
}

export function navigate(...parts) {
  const [page, id] = parts;
  if (page === 'runs' && id) go('runs', { id });
  else go(page || 'runs', {});
}

/** Turns a `#mm-arch/...` link into a shell navigation. Other links are left alone. */
export function followLink(event) {
  const anchor = event.target instanceof Element ? event.target.closest('a') : null;
  const link = anchor?.getAttribute('href') ?? '';
  if (!link.startsWith('#mm-arch/')) return;
  event.preventDefault();
  const parts = link.slice('#mm-arch/'.length).split('/').filter(Boolean).map((part) => decodeURIComponent(part));
  navigate(...parts);
}
