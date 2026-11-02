import { cn } from '@/shared/utils/cn';

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        // `card` is a stable hook for the browser tests (tests/ui_smoke.py); it carries no style.
        'card rounded-[var(--radius-lg)] border border-[var(--color-gray-100)] bg-[var(--color-surface)] shadow-[var(--shadow-sm)]',
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex flex-col gap-1 border-b border-[var(--color-gray-100)] p-5', className)}
      {...props}
    />
  );
}

/** A card's title. An h2 by default, because the page's own title is the h1; use `as="h3"` for a card inside a section with its own h2. */
export function CardTitle({
  className,
  as: Heading = 'h2',
  ...props
}: React.HTMLAttributes<HTMLHeadingElement> & { as?: 'h2' | 'h3' }) {
  return (
    <Heading
      className={cn('text-lg font-semibold text-[var(--color-gray-900)]', className)}
      {...props}
    />
  );
}

export function CardDescription({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-sm text-[var(--color-gray-500)]', className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-5', className)} {...props} />;
}
