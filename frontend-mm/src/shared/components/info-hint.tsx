'use client';

import { Info } from 'lucide-react';
import { useRef, useState } from 'react';

import { Button } from '@/shared/design-system/ui/button';
import { Modal } from '@/shared/design-system/ui/modal';

/**
 * The "i" beside a label or a card title: opens a small dialog that explains it (never a hover tooltip, which a phone cannot show and a
 * keyboard cannot reach). Enter or Space opens it, Escape or Close closes it, and focus goes back to the "i". Blank lines in `text`
 * start a new paragraph.
 */
export function InfoHint({ label, text, disabled = false }: { label: string; text: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const paragraphs = text.split(/\n{2,}/).map((part) => part.trim()).filter(Boolean);

  return (
    <>
      <button
        ref={trigger}
        type="button"
        disabled={disabled}
        aria-label={`About ${label}`}
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        className="inline-flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded-full text-[var(--color-gray-500)] hover:bg-[var(--color-primary-50)] hover:text-[var(--color-primary-700)] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Info className="pointer-events-none h-3.5 w-3.5" aria-hidden />
      </button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title={label}
        onCloseAutoFocus={(event) => {
          // Opened from code, not from a Radix trigger: send focus back to the "i" ourselves (Safari does not focus a button on click).
          event.preventDefault();
          trigger.current?.focus();
        }}
        footer={
          <Button type="button" onClick={() => setOpen(false)}>
            Close
          </Button>
        }
      >
        <div className="space-y-3 text-sm leading-6 whitespace-pre-line text-[var(--color-gray-700)]">
          {paragraphs.map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </div>
      </Modal>
    </>
  );
}
