/** A half-dial of how many ratings are in. While scoring is running it is the one motion on the page. */
export function ReadinessMark({ done, total, busy }: { done: number; total: number; busy?: boolean }) {
  const share = total > 0 ? Math.min(1, done / total) : 0;
  const label = busy ? 'Scoring the questionnaire' : `${done} of ${total} ratings in`;
  return (
    <svg viewBox="0 0 88 52" className={busy ? 'mra-gauge mra-gauge-busy h-16 w-24' : 'mra-gauge h-16 w-24'} role="img" aria-label={label}>
      <path d="M8 44 A36 36 0 0 1 80 44" fill="none" stroke="var(--color-primary-100)" strokeWidth="6" strokeLinecap="round" />
      <path
        className="mra-gauge-fill"
        d="M8 44 A36 36 0 0 1 80 44"
        fill="none"
        stroke="var(--color-primary-600)"
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={`${busy ? 40 : share * 113} 113`}
      />
    </svg>
  );
}
