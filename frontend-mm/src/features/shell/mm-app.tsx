'use client';

import { Dashboard } from '@/features/shell/dashboard';
import { AuthGate } from '@/shared/auth/auth-gate';

/** One sign-in for everything: the sign-in page for anyone who is not signed in, the dashboard for everyone who is. */
export function MmApp() {
  return (
    <AuthGate>
      <Dashboard />
    </AuthGate>
  );
}
