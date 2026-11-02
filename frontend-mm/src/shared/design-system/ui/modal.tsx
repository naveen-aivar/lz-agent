'use client';

import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/shared/utils/cn';

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  size = 'md',
  footer,
  onCloseAutoFocus,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  /** `xl` is for document/PDF viewers that need room. */
  size?: 'md' | 'xl';
  /** Buttons along the foot, aligned to the right (the dialog's own actions, or a Close button for an information dialog). */
  footer?: React.ReactNode;
  /**
   * Called when the dialog has closed and focus is about to go back. Call `event.preventDefault()` and focus the element that opened it
   * when the dialog was opened from code rather than from a Radix trigger (it is not always the element that had focus).
   */
  onCloseAutoFocus?: (event: Event) => void;
  children?: React.ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay fixed inset-0 z-50 bg-[rgba(18,25,38,0.45)]" />
        <Dialog.Content
          // Without a description there is nothing for aria-describedby to point at; saying so keeps Radix from warning.
          {...(description ? {} : { 'aria-describedby': undefined })}
          onCloseAutoFocus={onCloseAutoFocus}
          className={cn(
            'modal-panel fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-2rem)] overflow-y-auto',
            size === 'xl' ? 'w-[min(64rem,calc(100%-2rem))]' : 'w-[min(32rem,calc(100%-2rem))]',
            'rounded-[var(--radius-lg)] bg-[var(--color-surface)] p-6 shadow-[var(--shadow-md)]',
          )}
        >
          <div className="flex items-start justify-between gap-4">
            <Dialog.Title className="text-lg font-semibold text-[var(--color-gray-900)]">
              {title}
            </Dialog.Title>
            <Dialog.Close
              aria-label="Close"
              className="inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] text-[var(--color-gray-500)] hover:bg-[var(--color-gray-100)]"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          {description ? (
            <Dialog.Description className="mt-3 text-sm leading-6 text-[var(--color-gray-600)]">{description}</Dialog.Description>
          ) : null}
          {children ? <div className="mt-4">{children}</div> : null}
          {footer ? <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
