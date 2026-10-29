import type { AuditItem } from "../api/client";
import { feedText } from "../logic/activity";
import { ago } from "../logic/format";

/** Events, already ordered newest first. */
export function AuditFeed({ audit, userSub }: { audit: AuditItem[]; userSub: string }) {
  if (!audit.length) return <p className="hint">Nothing recorded yet.</p>;
  return (
    <ol className="feed">
      {audit.map((a) => (
        <li key={a.SK} className={/failed/.test(a.action) ? "bad" : ""}>
          <time dateTime={new Date(a.ts * 1000).toISOString()} title={new Date(a.ts * 1000).toLocaleString()}>{ago(a.ts)}</time>
          <span>{feedText(a, userSub)}</span>
        </li>
      ))}
    </ol>
  );
}
