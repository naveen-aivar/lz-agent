import { cn } from '@/shared/utils/cn';

/** "Arun Sharma" is "AS": the first letter of the first and the last word. */
export function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return '?';
  const first = Array.from(words[0])[0] ?? '';
  const last = words.length > 1 ? (Array.from(words[words.length - 1])[0] ?? '') : '';
  return `${first}${last}`.toUpperCase();
}

const SIZES = { sm: 'h-7 w-7 text-xs', md: 'h-9 w-9 text-sm' } as const;

/** The signed-in person as their initials in the brand blue (sign-in does not give a photo). Decorative: the name is written beside it. */
export function UserAvatar({ name, size = 'md', className }: { name: string; size?: keyof typeof SIZES; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full bg-[var(--color-primary-600)] font-bold text-white select-none',
        SIZES[size],
        className,
      )}
    >
      {initialsOf(name)}
    </span>
  );
}
