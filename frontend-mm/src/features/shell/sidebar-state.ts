'use client';

import { useSyncExternalStore } from 'react';

const KEY = 'mm.sidebar.collapsed';
const listeners = new Set<() => void>();

/** Narrower than this, the agents' pages need the room more than the labels do (the agents' own layouts were made for a full-width window). */
const NARROW = '(max-width: 1099px)';

const read = (): boolean => {
  try {
    const stored = window.localStorage.getItem(KEY);
    if (stored === 'true' || stored === 'false') return stored === 'true';
  } catch {
    /* blocked storage: fall through to the window's own size */
  }
  return typeof window.matchMedia === 'function' && window.matchMedia(NARROW).matches;
};

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** Whether the sidebar shows icons only: the person's own choice when they made one (kept on this device), otherwise icons only in a narrow window; the same on the server and on the first draw, so a static page never mismatches. */
export function useSidebarCollapsed(): [boolean, (next: boolean) => void] {
  const collapsed = useSyncExternalStore(subscribe, read, () => false);
  const set = (next: boolean) => {
    try {
      window.localStorage.setItem(KEY, String(next));
    } catch {
      /* blocked storage: the choice just is not kept */
    }
    listeners.forEach((listener) => listener());
  };
  return [collapsed, set];
}
