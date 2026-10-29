import type { RunSummary } from "../api/client";
import { ago, pretty, stateOf } from "../logic/format";

import { Badge } from "../ui/Badge";
export { Badge };

/** The run list: customer, type, age, state, short id, and the way in. */
export function RunsTable({ runs, onDeploy, empty }: { runs: RunSummary[]; onDeploy?: (designRunId: string) => void; empty?: string }) {
  if (!runs.length) return <p className="empty">{empty ?? <>No runs yet. <a href="#/new">Start a design run</a>.</>}</p>;
  return (
    <div className="tbl-wrap">
      <table>
        <thead><tr><th>Customer</th><th>Type</th><th>Started</th><th>State</th><th>Run</th><th /></tr></thead>
        <tbody>
          {runs.map((r) => {
            const [tone, label] = stateOf(r.status);
            const deploy = r.runKind === "deploy";
            return (
              <tr key={r.runId} className="click">
                <td className="name"><a href={`#/run/${r.runId}`}>{pretty(r.customerId) || r.runId.slice(0, 8)}</a></td>
                <td><Badge tone={deploy ? "violet" : "muted"}>{deploy ? "Deploy" : "Design"}</Badge></td>
                <td>{ago(r.createdAt)}</td>
                <td><Badge tone={tone}>{label}</Badge>{r.awaitingHitl && r.status === "RUNNING" && <> <Badge tone="amber">Needs you</Badge></>}</td>
                <td><code>{r.runId.slice(0, 8)}</code></td>
                <td>
                  {r.status === "FAILED" && r.error && <span className="errtext">{r.error.slice(0, 80)} </span>}
                  <a href={`#/run/${r.runId}`}>View →</a>
                  {onDeploy && !deploy && r.status === "DELIVERED" && (
                    <> <button type="button" className="btn btn-sm" onClick={() => onDeploy(r.runId)}>Deploy</button></>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
