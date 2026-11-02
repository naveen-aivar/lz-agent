/** Pages gathering into a folder. It loops only while a package is being built. */
export function PackageMark({ busy }: { busy?: boolean }) {
  return (
    <svg viewBox="0 0 88 64" className={busy ? 'cva-pack cva-pack-busy h-16 w-20' : 'cva-pack h-16 w-20'} role="img" aria-label={busy ? 'Building the package' : 'Package'}>
      <path d="M6 28 h76 v28 h-76 z" fill="var(--color-primary-50)" stroke="var(--color-primary-600)" strokeWidth="2" />
      <path d="M6 28 h24 l6-8 h22" fill="none" stroke="var(--color-primary-600)" strokeWidth="2" />
      <rect className="cva-sheet cva-sheet-1" x="22" y="8" width="36" height="24" rx="2" fill="white" stroke="var(--color-primary-300)" />
      <rect className="cva-sheet cva-sheet-2" x="26" y="12" width="36" height="24" rx="2" fill="white" stroke="var(--color-primary-400)" />
      <rect className="cva-sheet cva-sheet-3" x="30" y="16" width="36" height="24" rx="2" fill="white" stroke="var(--color-primary-600)" />
    </svg>
  );
}
