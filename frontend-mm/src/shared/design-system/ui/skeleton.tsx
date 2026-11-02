import { cn } from '@/shared/utils/cn';

/**
 * A placeholder shaped like the thing that is loading, so nothing moves when the data arrives. Purely visual: it is hidden from screen
 * readers, so the loading region that holds it should say what is loading (role="status" and a label).
 */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('skeleton-block rounded-[var(--radius-md)]', className)} />;
}

/**
 * Real text drawn invisibly over a placeholder bar: the bar takes the exact width and height the loaded text will have, so the page does
 * not shift. Pass the text the real value will look like.
 */
export function SkeletonText({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span aria-hidden className={cn('skeleton-block inline-block max-w-full rounded-[var(--radius-sm)] align-middle text-transparent select-none', className)}>
      {children}
    </span>
  );
}
