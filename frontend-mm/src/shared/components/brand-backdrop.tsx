/**
 * Decorative backdrop from the ingrammicro.com hero, which scales the Ingram wordmark up until
 * only the curves of its letters show. Two crops of that artwork (public/brand, recoloured to
 * our blues) sit in opposite corners, sized to stay clear of the page header text.
 * Purely visual, so it is hidden from assistive tech and ignores pointer events.
 */
export function BrandBackdrop() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden opacity-[var(--backdrop-opacity)]"
    >
      <div className="absolute top-0 right-0 aspect-[465/380] w-[26vw] max-w-[32rem] bg-[url(/brand/ingram-curve-top-right.svg)] bg-contain bg-top-right bg-no-repeat" />
      <div className="absolute bottom-0 left-0 aspect-[380/320] w-[32vw] max-w-[34rem] bg-[url(/brand/ingram-curve-bottom-left.svg)] bg-contain bg-bottom-left bg-no-repeat" />
    </div>
  );
}
