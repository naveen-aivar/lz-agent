import { useEffect, useState } from "react";
import type { Client, RunSummary } from "../api/client";
import { statusTone } from "../logic/status";
import { DeployDialog } from "./DeployDialog";

export function RunsPage({ api, onOpen }: { api: Client; onOpen: (runId: string) => void }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState("");
  const [deployFor, setDeployFor] = useState<string | null>(null);

  useEffect(() => {
    api.listRuns().then((r) => setRuns(r.runs)).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [api]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!runs) return <p>Loading…</p>;
  return (
    <div>
      <h1>Runs</h1>
      <table>
        <thead><tr><th>Customer</th><th>Kind</th><th>Status</th><th>Started</th><th /></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.runId}>
              <td><a href={`#/run/${r.runId}`} onClick={(e) => { e.preventDefault(); onOpen(r.runId); }}>{r.customerId ?? r.runId.slice(0, 8)}</a></td>
              <td>{r.runKind === "deploy" ? "deploy" : "design"}</td>
              <td><span className={`badge badge-${statusTone(r.status)}`}>{r.status}</span></td>
              <td>{new Date(r.createdAt * 1000).toLocaleString()}</td>
              <td>{r.runKind !== "deploy" && r.status === "DELIVERED" && (
                <button type="button" className="btn btn-sm" onClick={() => setDeployFor(r.runId)}>Deploy</button>)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {deployFor && <DeployDialog designRunId={deployFor} api={api} onCancel={() => setDeployFor(null)} onStarted={(id) => { setDeployFor(null); onOpen(id); }} />}
    </div>
  );
}
