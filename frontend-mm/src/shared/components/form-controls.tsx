'use client';

import { useId } from 'react';
import { InfoHint } from '@/shared/components/info-hint';
import { cn } from '@/shared/utils/cn';

/** A label with an optional "i" that explains the field, and a note when it can be left empty. */
export function FieldLabel({
  htmlFor,
  label,
  hint,
  optional,
}: {
  htmlFor?: string;
  label: string;
  hint?: string;
  optional?: boolean;
}) {
  return (
    <div className="flex items-center gap-1.5">
      {htmlFor ? (
        <label htmlFor={htmlFor} className="text-sm font-medium text-[var(--color-gray-900)]">
          {label}
        </label>
      ) : (
        <span className="text-sm font-medium text-[var(--color-gray-900)]">{label}</span>
      )}
      {hint ? <InfoHint label={label} text={hint} /> : null}
      {optional ? <span className="text-xs text-[var(--color-gray-500)]">optional</span> : null}
    </div>
  );
}

/**
 * A field as one line: its label (and "i") on the left, the control after it. On a narrow screen the
 * label sits above. Group fields side by side by putting rows in a grid.
 */
export function FormRow({
  label,
  hint,
  htmlFor,
  align = 'center',
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  /** `start` for a tall control, so the label lines up with its first line. */
  align?: 'center' | 'start';
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        'grid gap-x-3 gap-y-1.5 sm:grid-cols-[7.5rem_minmax(0,1fr)]',
        align === 'start' ? 'sm:items-start' : 'sm:items-center',
      )}
    >
      <div className={cn('whitespace-nowrap', align === 'start' && 'sm:pt-2')}>
        <FieldLabel htmlFor={htmlFor} label={label} hint={hint} />
      </div>
      <div className="min-w-0 space-y-1.5">{children}</div>
    </div>
  );
}

export const controlClass =
  'w-full rounded-[var(--radius-md)] border bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-gray-900)] outline-none placeholder:text-[var(--color-gray-500)] focus:border-[var(--color-primary-600)] focus:ring-4 focus:ring-[var(--color-primary-100)] disabled:cursor-not-allowed disabled:opacity-60';

const borderFor = (invalid?: boolean) =>
  invalid ? 'border-[var(--color-danger-700)]' : 'border-[var(--color-gray-300)]';

export function FieldError({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <p id={id} role="alert" className="text-xs text-[var(--color-danger-700)]">
      {children}
    </p>
  );
}

export function FieldNote({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-[var(--color-gray-500)]">{children}</p>;
}

type TextInputProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, 'className'> & {
  invalid?: boolean;
  className?: string;
};

export function TextInput({ invalid, className, ...props }: TextInputProps) {
  return (
    <input
      {...props}
      aria-invalid={invalid || undefined}
      className={cn(controlClass, borderFor(invalid), className)}
    />
  );
}

type TextAreaProps = Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, 'className'> & {
  invalid?: boolean;
  className?: string;
};

export function TextArea({ invalid, className, ...props }: TextAreaProps) {
  return (
    <textarea
      {...props}
      aria-invalid={invalid || undefined}
      className={cn(controlClass, borderFor(invalid), 'resize-y', className)}
    />
  );
}

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
}

/** A row of options, one of which is chosen: real radio buttons, so arrow keys and screen readers work. */
export function SegmentedControl<T extends string>({
  legend,
  value,
  options,
  onChange,
  disabled,
  size = 'md',
}: {
  legend: string;
  value: T;
  options: readonly SegmentOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  /** `sm` is for a filter above a list. */
  size?: 'md' | 'sm';
}) {
  const name = useId();
  return (
    <fieldset className="min-w-0" disabled={disabled}>
      <legend className="sr-only">{legend}</legend>
      <div className="grid auto-cols-fr grid-flow-col gap-1 rounded-[var(--radius-md)] bg-[var(--color-gray-100)] p-1">
        {options.map((option) => (
          <label key={option.value} className="relative block cursor-pointer">
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              disabled={option.disabled}
              onChange={() => onChange(option.value)}
              className="peer sr-only"
            />
            <span
              className={cn(
                'flex h-full flex-col rounded-[calc(var(--radius-md)-2px)] text-[var(--color-gray-600)] transition-colors',
                size === 'sm' ? 'items-center px-2.5 py-1 text-xs' : 'px-3 py-2 text-sm',
                'peer-checked:bg-[var(--color-surface)] peer-checked:text-[var(--color-primary-700)] peer-checked:shadow-[var(--shadow-sm)]',
                'peer-focus-visible:ring-4 peer-focus-visible:ring-[var(--color-primary-100)] peer-disabled:cursor-not-allowed peer-disabled:opacity-50',
                'hover:text-[var(--color-gray-900)]',
              )}
            >
              <span className="font-medium">{option.label}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** A label, a text input, and an optional hint below it. The input's id is generated, so labels always connect. */
export function TextField({
  label,
  value,
  onChange,
  hint,
  help,
  error,
  optional,
  className,
  inputClassName,
  ...inputProps
}: Omit<TextInputProps, 'value' | 'onChange' | 'className' | 'id'> & {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Explains the field in the "i" tooltip. */
  hint?: string;
  /** Always-visible note under the input, e.g. the expected format. */
  help?: string;
  error?: string;
  optional?: boolean;
  className?: string;
  inputClassName?: string;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <FieldLabel htmlFor={id} label={label} hint={hint} optional={optional} />
      <TextInput
        {...inputProps}
        id={id}
        value={value}
        invalid={Boolean(error)}
        aria-describedby={error || help ? noteId : undefined}
        onChange={(e) => onChange(e.target.value)}
        className={inputClassName}
      />
      {error ? <FieldError id={noteId}>{error}</FieldError> : help ? <FieldNote>{help}</FieldNote> : null}
    </div>
  );
}

/** A real checkbox with its label, sized and coloured to match the other controls. */
export function CheckboxField({
  label,
  checked,
  onChange,
  description,
  disabled,
  className,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  description?: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <label className={cn('flex cursor-pointer items-start gap-2.5', disabled && 'cursor-not-allowed opacity-60', className)}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded-[var(--radius-sm)] border-[var(--color-gray-300)] accent-[var(--color-primary-600)] focus-visible:ring-4 focus-visible:ring-[var(--color-primary-100)] focus-visible:outline-none"
      />
      <span className="min-w-0">
        <span className="block text-sm font-medium text-[var(--color-gray-900)]">{label}</span>
        {description ? <span className="block text-xs text-[var(--color-gray-500)]">{description}</span> : null}
      </span>
    </label>
  );
}
