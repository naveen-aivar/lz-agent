import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { Loader2 } from 'lucide-react';
import { cn } from '@/shared/utils/cn';

const buttonVariants = cva(
  'inline-flex cursor-pointer items-center justify-center gap-2 font-semibold whitespace-nowrap transition-all select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary-600)] disabled:cursor-not-allowed disabled:opacity-50 data-[loading=true]:disabled:cursor-progress data-[loading=true]:disabled:opacity-100',
  {
    variants: {
      variant: {
        primary:
          'rounded-[var(--radius-pill)] border border-[var(--color-primary-600)] bg-[var(--color-primary-600)] text-white shadow-[var(--shadow-sm)] [&:not(:disabled)]:hover:border-[var(--color-primary-hover)] [&:not(:disabled)]:hover:bg-[var(--color-primary-hover)]',
        secondary:
          'rounded-[var(--radius-pill)] border border-[var(--color-primary-200)] bg-[var(--color-surface)] text-[var(--color-primary-700)] shadow-[var(--shadow-sm)] [&:not(:disabled)]:hover:bg-[var(--color-primary-100)]',
        tertiary:
          'rounded-[var(--radius-pill)] border border-transparent bg-[var(--color-surface)] text-[var(--color-primary-700)] [&:not(:disabled)]:hover:bg-[var(--color-primary-50)]',
        // Not in the WAFR set: the same pill, in the danger tone, for Reject and Delete.
        danger:
          'rounded-[var(--radius-pill)] border border-[color-mix(in_srgb,var(--color-danger-700)_35%,transparent)] bg-[var(--color-surface)] text-[var(--color-danger-700)] shadow-[var(--shadow-sm)] [&:not(:disabled)]:hover:border-[var(--color-danger-700)] [&:not(:disabled)]:hover:bg-[var(--color-danger-50)]',
        ghost:
          'rounded-[var(--radius-md)] border border-transparent bg-transparent text-[var(--color-gray-700)] [&:not(:disabled)]:hover:bg-[var(--color-gray-100)]',
        // A step's forward button (see StepNextButton): pale until the step is done, with a solid
        // layer (`data-fill`, set by StepNextButton) that grows over it from the left. The pale
        // look is the old disabled look, drawn with colour rather than opacity so the fill stays solid.
        step: 'relative isolate overflow-hidden rounded-[var(--radius-pill)] border border-[color-mix(in_srgb,var(--color-primary-600)_50%,transparent)] bg-[color-mix(in_srgb,var(--color-primary-600)_50%,transparent)] text-white shadow-[var(--shadow-sm)] transition-[box-shadow,border-color] duration-[var(--next-fill-ms,600ms)] disabled:opacity-100 data-[solid=true]:border-[var(--color-primary-600)] [&:not(:disabled):hover]:border-[var(--color-primary-hover)] [&:not(:disabled):hover>[data-fill]]:bg-[var(--color-primary-hover)]',
      },
      size: {
        sm: 'px-3.5 py-2 text-sm leading-5',
        md: 'px-4 py-2.5 text-sm leading-5',
        lg: 'px-[18px] py-2.5 text-base leading-6',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Shows a spinner and blocks clicks while an action is in flight. Ignored with `asChild`. */
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, children, ...props }, ref) => {
    if (asChild) {
      return (
        <Slot className={cn(buttonVariants({ variant, size, className }))} data-variant={variant ?? 'primary'} ref={ref} {...props}>
          {children}
        </Slot>
      );
    }
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        data-variant={variant ?? 'primary'}
        ref={ref}
        {...props}
        disabled={loading || props.disabled}
        data-loading={loading || undefined}
        aria-busy={loading || undefined}
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
        {children}
      </button>
    );
  },
);
Button.displayName = 'Button';
