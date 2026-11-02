'use client';

import { useEffect } from 'react';
import { Toaster as Sonner, toast } from 'sonner';

/**
 * success (green): it is done. warning (amber): it worked but is incomplete or out of date (some figures missing, a refresh failed and
 * the last figures stay, one of several reports failed). danger (red): what was asked for failed and there is nothing to show.
 */
export type ToastMessage = {
  title: string;
  description?: string;
  variant?: 'success' | 'warning' | 'danger';
  /** A repeat with the same id replaces the toast instead of stacking another. */
  id?: string;
};

const TOAST_DURATION_MS = 4_000;
/** A warning or an error needs time to read, and says what to do next. */
const ERROR_TOAST_DURATION_MS = 9_000;

function showToast({ title, description, variant, id }: ToastMessage) {
  if (variant === 'danger') {
    toast.error(title, { description, id, duration: ERROR_TOAST_DURATION_MS });
  } else if (variant === 'warning') {
    toast.warning(title, { description, id, duration: ERROR_TOAST_DURATION_MS });
  } else {
    toast.success(title, { description, id, duration: TOAST_DURATION_MS });
  }
}

/** Shows a toast. Kept as a hook so call sites stay the same whichever library renders it. */
export function useToast() {
  return showToast;
}

/**
 * Toasts whenever `message` becomes set, so a failure is never silent (the page shows it inline too). `variant` is red (danger) unless the
 * page still has something to show, then amber (warning). The title is the id, so a repeat replaces the toast instead of stacking.
 */
export function useFailureToast(title: string, message: string | null | undefined, variant: 'warning' | 'danger' = 'danger') {
  useEffect(() => {
    if (message) showToast({ title, description: message, variant, id: title });
  }, [title, message, variant]);
}

/**
 * Renders toasts with Sonner (shadcn/ui's toast component) in the top-right corner, coloured from
 * the design tokens so they follow the app's theme.
 */
export function ToasterProvider({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <Sonner
        position="top-right"
        richColors
        closeButton
        className="font-[family-name:var(--font-sans)]"
        style={
          {
            '--normal-bg': 'var(--color-surface)',
            '--normal-text': 'var(--color-gray-900)',
            '--normal-border': 'var(--color-gray-100)',
            '--success-bg': 'var(--color-success-50)',
            '--success-text': 'var(--color-success-700)',
            '--success-border': 'var(--color-success-700)',
            '--warning-bg': 'var(--color-warning-50)',
            '--warning-text': 'var(--color-warning-700)',
            '--warning-border': 'var(--color-warning-700)',
            '--error-bg': 'var(--color-danger-50)',
            '--error-text': 'var(--color-danger-700)',
            '--error-border': 'var(--color-danger-700)',
            '--border-radius': 'var(--radius-md)',
          } as React.CSSProperties
        }
      />
    </>
  );
}
