import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';

import { cn } from '@/shared/utils/cn';

type Tone = 'success' | 'danger' | 'warning' | 'info';

const TONES: Record<Tone, { box: string; icon: React.ComponentType<{ className?: string }> }> = {
  success: {
    box: 'border-[var(--color-success-700)]/20 bg-[var(--color-success-50)] text-[var(--color-success-700)]',
    icon: CheckCircle2,
  },
  danger: {
    box: 'border-[var(--color-danger-700)]/20 bg-[var(--color-danger-50)] text-[var(--color-danger-700)]',
    icon: XCircle,
  },
  warning: {
    box: 'border-[var(--color-warning-700)]/20 bg-[var(--color-warning-50)] text-[var(--color-warning-700)]',
    icon: AlertTriangle,
  },
  info: {
    box: 'border-[var(--color-primary-200)] bg-[var(--color-primary-25)] text-[var(--color-gray-700)]',
    icon: Info,
  },
};

/** An inline message about the result of an action or the state of a section. Errors are announced at once. */
export function Notice({
  tone = 'info',
  title,
  children,
  className,
}: {
  tone?: Tone;
  title?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const { box, icon: Icon } = TONES[tone];
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={cn('flex items-start gap-2.5 rounded-[var(--radius-md)] border px-3.5 py-3 text-sm', box, className)}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 space-y-0.5">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className="break-words">{children}</div> : null}
      </div>
    </div>
  );
}
