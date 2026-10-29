export const Badge = ({ tone, children }: { tone: string; children: string }) => <span className={`badge badge-${tone}`}>{children}</span>;
