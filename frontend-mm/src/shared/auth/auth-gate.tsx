'use client';

import { useEffect, type ReactNode } from 'react';

import { refreshAuth, useAuth } from './auth-store';
import { LoginPage } from './login-page';

/**
 * Shows the app to a signed-in person and the sign-in page to anyone else. With sign-in not configured the app is shown as it is.
 * Nothing under it (and so no call to the API) starts before the person is signed in.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  useEffect(() => {
    void refreshAuth();
  }, []);
  if (auth.status === 'signed-in') return <>{children}</>;
  return <LoginPage checking={auth.status === 'checking'} />;
}
