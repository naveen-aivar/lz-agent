import { useMemo, useState } from "react";
import type { Client } from "../api/client";
import { countByStatus, filterRuns } from "../logic/runs";
import type { KindFilter, StatusFilter } from "../logic/runs";
import { PAGE_SIZE } from "../logic/stats";
import { DeployDialog } from "./DeployDialog";
import { RunsTable } from "./RunsTable";
import { useRuns } from "./useRuns";
const STATUS: [StatusFilter, string][] = [["all", "All"], ["attention", "Needs you"], ["active", "In progress"], ["delivered", "Delivered"], ["failed", "Failed"]];
const KIND: [KindFilter, string][] = [["all", "All types"], ["design", "Design"], ["deploy", "Deploy"]];
export function RunsPage({ api, onOpen }: { api: Client; onOpen: (runId: string) => void }) {
  const { runs, total, error } = useRuns(api);
  const [deployFor, setDeployFor] = useState<string | null>(null);
  const [shown, setShown] = useState(PAGE_SIZE);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [kind, setKind] = useState<KindFilter>("all");
  const [query, setQuery] = useState("");
  const counts = useMemo(() => (runs ? countByStatus(runs) : null), [runs]);
  const rows = useMemo(() => (runs ? filterRuns(runs, { status, kind, query }) : []), [runs, status, kind, query]);
  if (error) return <p className="errtext" role="alert">{error}</p>;
  if (!runs || !counts) return <p className="empty">Loading…</p>;
  return (
    <>
      <div className="page-head">
        <div><h1 className="page-title">Runs</h1><p className="page-sub">Design runs turn a SOW into code. Deploy runs build it in an AWS account. A deploy run that stopped can be resumed.</p></div>
        <a className="btn btn-primary" href="#/new">New design run</a>
      </div>
      <div className="panel panel-pad">
        <div className="filters">
          <div className="chips" role="group" aria-label="Filter by state">
            {STATUS.map(([id, label]) => (
              <button key={id} type="button" className="chip" aria-pressed={status === id} onClick={() => { setStatus(id); setShown(PAGE_SIZE); }}>
                {label} <span className="count">{counts[id]}</span>
              </button>
            ))}
          </div>
          <select aria-label="Filter by type" value={kind} onChange={(e) => { setKind(e.target.value as KindFilter); setShown(PAGE_SIZE); }} className="select-s">
            {KIND.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
          <input type="search" aria-label="Search runs" placeholder="Search customer or run id" value={query} onChange={(e) => { setQuery(e.target.value); setShown(PAGE_SIZE); }} className="search" />
        </div>
        <RunsTable runs={rows.slice(0, shown)} onDeploy={setDeployFor} empty={runs.length ? "No runs match these filters." : undefined} />
        <div className="card-head" style={{ marginTop: 12 }}>
          <span className="hint" data-testid="run-count">
            Showing {Math.min(shown, rows.length)} of {rows.length} matching runs ({total ?? runs.length} in total)
            {total !== undefined && total > runs.length ? `; only the newest ${runs.length} can be listed` : ""}
          </span>
          {shown < rows.length && (
            <button type="button" className="btn btn-sm" onClick={() => setShown(shown + PAGE_SIZE)}>Show {Math.min(PAGE_SIZE, rows.length - shown)} more</button>
          )}
        </div>
      </div>
      {deployFor && (
        <DeployDialog designRunId={deployFor} api={api} onCancel={() => setDeployFor(null)}
          onStarted={(id) => { setDeployFor(null); onOpen(id); }} />
      )}
    </>
  );
}
