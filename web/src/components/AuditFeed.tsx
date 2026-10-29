import type { AuditItem } from "../api/client";

const tsOf = (sk: string): number => Number(sk.split("#")[1] ?? 0);
const noise = new Set(["deploy.sequencer.step", "phase.started", "phase.continue", "tool.transform_poll_analyze_job"]);

/** The audit log, newest first. Routine polling rows are hidden unless `all` is set. */
export function AuditFeed({ audit, all = false }: { audit: AuditItem[]; all?: boolean }) {
  const rows = [...audit].sort((a, b) => tsOf(b.SK) - tsOf(a.SK)).filter((a) => all || !noise.has(a.action));
  if (!rows.length) return <p className="hint">Nothing recorded yet.</p>;
  return (
    <ul className="feed">
      {rows.map((a) => {
        let detail = "";
        try {
          const d = a.detail ? (JSON.parse(a.detail) as Record<string, unknown>) : {};
          detail = String(d.title ?? d.reason ?? d.text ?? d.option ?? d.error ?? "");
        } catch {
          detail = "";
        }
        return (
          <li key={a.SK}>
            <time dateTime={new Date(tsOf(a.SK) * 1000).toISOString()}>{new Date(tsOf(a.SK) * 1000).toLocaleTimeString()}</time>{" "}
            <code>{a.action}</code> <span className="hint">{a.actor === "agent" ? "deploy agent" : a.actor === "system" ? "platform" : "a person"}</span>
            {detail && <div className="detail">{detail.slice(0, 300)}</div>}
          </li>
        );
      })}
    </ul>
  );
}
