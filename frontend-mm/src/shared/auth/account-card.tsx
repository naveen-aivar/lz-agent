'use client';

import { LogOut } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/shared/design-system/ui/button';
import { cn } from '@/shared/utils/cn';

import { displayName, signOutNow, useAuth } from './auth-store';
import { authEnabled } from './config';
import { UserAvatar } from './user-avatar';

/**
 * The signed-in person at the foot of the sidebar: their avatar, name and email, and Sign out. When the sidebar is collapsed only the avatar
 * and a sign-out button are drawn. Nothing is drawn when sign-in is not configured (there is no one to sign out).
 */
export function AccountCard({ collapsed = false, disabled = false }: { collapsed?: boolean; disabled?: boolean }) {
  const auth = useAuth();
  const [busy, setBusy] = useState(false);
  if (!authEnabled || auth.status !== 'signed-in' || !auth.email) return null;
  // While an agent opens, the person's card stays where it will be, switched off.
  const name = displayName(auth);
  const signOut = () => {
    setBusy(true);
    void signOutNow().finally(() => setBusy(false));
  };

  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-2 px-2 pb-3">
        <span title={`${name} · ${auth.email}`}>
          <UserAvatar name={name} />
          <span className="sr-only">
            Signed in as {name}, {auth.email}
          </span>
        </span>
        <button
          type="button"
          onClick={signOut}
          disabled={busy || disabled}
          title="Sign out"
          aria-label="Sign out"
          className="inline-flex h-9 w-9 cursor-pointer items-center justify-center rounded-[var(--radius-md)] text-[var(--color-gray-500)] hover:bg-[var(--color-gray-100)] hover:text-[var(--color-gray-900)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <LogOut className="h-[18px] w-[18px]" aria-hidden />
        </button>
      </div>
    );
  }

  return (
    <div className={cn('mx-3 mb-3 flex flex-col gap-3 rounded-[var(--radius-md)] border border-[var(--color-gray-100)] bg-[var(--color-gray-25)] p-3', disabled && 'opacity-60')}>
      <div className="flex min-w-0 items-center gap-2.5">
        <UserAvatar name={name} />
        <div className="min-w-0">
          <p className="truncate text-sm leading-5 font-bold text-[var(--color-gray-900)]" title={name}>
            {name}
          </p>
          <p className="truncate text-xs leading-4 text-[var(--color-gray-600)]" title={auth.email}>
            {auth.email}
          </p>
        </div>
      </div>
      <Button type="button" variant="secondary" size="sm" className="w-full" loading={busy} disabled={disabled} onClick={signOut}>
        <LogOut className="h-4 w-4" aria-hidden />
        Sign out
      </Button>
    </div>
  );
}
