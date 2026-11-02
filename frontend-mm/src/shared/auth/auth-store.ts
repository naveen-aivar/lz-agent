import { useSyncExternalStore } from 'react';

import { currentSession, signOut as endSession } from './cognito';
import { authEnabled } from './config';

/** Who is signed in. Without sign-in configured, everyone is "signed-in". */
export interface AuthState {
  status: 'checking' | 'signed-out' | 'signed-in';
  email: string | null;
  /** "" when the account has no name. */
  name: string;
}

const SIGNED_OUT: AuthState = { status: 'signed-out', email: null, name: '' };
let state: AuthState = authEnabled ? { status: 'checking', email: null, name: '' } : { status: 'signed-in', email: null, name: '' };
const listeners = new Set<() => void>();
const set = (next: AuthState) => {
  state = next;
  listeners.forEach((listener) => listener());
};

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
const read = () => state;

export const useAuth = (): AuthState => useSyncExternalStore(subscribe, read, read);

/** Looks for a session kept in this tab (after a sign-in, or when the page opens). */
export async function refreshAuth(): Promise<void> {
  if (!authEnabled) return;
  try {
    const session = await currentSession();
    set(session ? { status: 'signed-in', email: session.email, name: session.name } : SIGNED_OUT);
  } catch {
    set(SIGNED_OUT);
  }
}

export async function signOutNow(): Promise<void> {
  try {
    await endSession();
  } finally {
    set(SIGNED_OUT);
  }
}

/** What to call the person: their name, else the first part of their address made readable ("jane.doe@example.com" -> "Jane Doe"). */
export function displayName({ name, email }: { name: string; email: string | null }): string {
  if (name) return name;
  const words = String(email ?? '')
    .split('@')[0]
    .replace(/[0-9]+/g, ' ')
    .split(/[._\-+\s]+/)
    .filter(Boolean);
  return words.length ? words.map((w) => w[0].toUpperCase() + w.slice(1)).join(' ') : String(email ?? '');
}
