'use client';

import { useEffect, useState } from 'react';

import { useAuth } from '@/shared/auth/auth-store';
import { controlClass } from '@/shared/components/form-controls';

const KEY = 'mm.cva.actor';

/** The signed-in person. Decisions are recorded against them. With sign-in off, the name typed on this tab is used. */
export function useActor(): { name: string; setName?: (value: string) => void } {
  const auth = useAuth();
  const signedIn = auth.email || auth.name;
  const [typed, setTyped] = useState('');
  useEffect(() => {
    if (signedIn) return;
    try {
      setTyped(sessionStorage.getItem(KEY) || '');
    } catch {
      /* this tab will ask again */
    }
  }, [signedIn]);
  if (signedIn) return { name: signedIn };
  return {
    name: typed,
    setName: (value: string) => {
      setTyped(value);
      try {
        sessionStorage.setItem(KEY, value);
      } catch {
        /* the name still applies to this view */
      }
    },
  };
}

export function NameField({ name, setName }: { name: string; setName?: (value: string) => void }) {
  if (!setName) return null;
  return (
    <label className="block text-sm">
      Your name
      <input className={`${controlClass} mt-1 max-w-sm`} value={name} maxLength={60} onChange={(event) => setName(event.target.value)} />
    </label>
  );
}
