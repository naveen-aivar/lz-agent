import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/shared/utils/cn';

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
  {
    variants: {
      variant: {
        default: 'bg-[var(--color-primary-50)] text-[var(--color-primary-700)]',
        success: 'bg-[var(--color-success-50)] text-[var(--color-success-700)]',
        warning: 'bg-[var(--color-warning-50)] text-[var(--color-warning-700)]',
        danger: 'bg-[var(--color-danger-50)] text-[var(--color-danger-700)]',
        muted: 'bg-[var(--color-gray-100)] text-[var(--color-gray-600)]',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
