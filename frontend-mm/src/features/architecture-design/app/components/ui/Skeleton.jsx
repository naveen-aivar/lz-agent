// A grey, pulsing stand-in for something still loading. Give it the size of the real thing.
export function Skeleton({ className = "", style }) {
  return <span aria-hidden className={`skeleton-block ${className}`.trim()} style={style} />;
}

// A stand-in for text that has not arrived. It holds an invisible example of that text, so the line has the
// height (and about the width) of the real one and nothing moves when the real text comes.
export function SkeletonText({ children, className = "" }) {
  return <span aria-hidden className={`skeleton-text ${className}`.trim()}>{children}</span>;
}
