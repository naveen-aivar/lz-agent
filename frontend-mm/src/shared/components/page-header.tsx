import { cn } from '@/shared/utils/cn';

/**
 * The page's heading: its title (the one h1), one short sentence, and the page's actions on the right. `eyebrow` names the group the page
 * belongs to; `meta` is a quiet row under the sentence with the settings that apply to this page.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  meta,
  actions,
  className,
}: {
  /** A small label above the title, such as the group the page belongs to. */
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** A quiet row under the description: the settings that apply to this page. */
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  /** Extra classes for the wrapper. It has no outer margin: the parent sets the spacing. */
  className?: string;
}) {
  return (
    <header className={cn('flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between', className)}>
      <div className="min-w-0">
        {eyebrow ? <p className="mb-1 text-xs font-semibold text-[var(--color-primary-700)]">{eyebrow}</p> : null}
        {/* Focused when the tab changes, so keyboard and screen-reader users land on the new page. */}
        <h1 id="page-title" tabIndex={-1} className="text-2xl leading-8 font-semibold text-[var(--color-gray-900)] outline-none">
          {title}
        </h1>
        {description ? <p className="mt-1 max-w-3xl text-sm text-[var(--color-gray-500)]">{description}</p> : null}
        {meta ? <div className="mt-4">{meta}</div> : null}
      </div>
      {actions ? (
        // Header buttons stand alone over the brand backdrop; only a SOLID blue button (the one main action) rests on a white pill, because
        // a pill around outlined buttons reads as a pill inside a pill. Text buttons get a white fill so they read over the corner.
        <div
          className={cn(
            'flex shrink-0 flex-wrap items-center gap-2 [&_[data-variant=ghost]]:bg-[var(--color-surface)]',
            'has-[[data-variant=primary],[data-variant=step]]:rounded-[var(--radius-pill)] has-[[data-variant=primary],[data-variant=step]]:border has-[[data-variant=primary],[data-variant=step]]:border-[var(--color-gray-100)] has-[[data-variant=primary],[data-variant=step]]:bg-[var(--color-surface)] has-[[data-variant=primary],[data-variant=step]]:p-1.5 has-[[data-variant=primary],[data-variant=step]]:shadow-[var(--shadow-sm)]',
          )}
        >
          {actions}
        </div>
      ) : null}
    </header>
  );
}
