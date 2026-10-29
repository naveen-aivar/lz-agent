import type { Client } from "../api/client";
import { pretty } from "../logic/format";
import { needsAttention } from "../logic/runs";
import { runStats } from "../logic/stats";
import { Kpi } from "../ui/Kpi";
import { RunsTable } from "./RunsTable";
import { useRuns } from "./useRuns";
export function DashboardPage({ api }: { api: Client }) {
  const { runs, error } = useRuns(api);
  if (error) return <p className="errtext" role="alert">{error}</p>;
  if (!runs) return <p className="empty">Loading…</p>;
  const s = runStats(runs);
  const waiting = runs.filter(needsAttention);
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Landing Zone</h1>
          <p className="page-sub">
            Turn a customer's statement of work into landing zone code, then build it with AWS Transform. The deploy agent answers
            Transform's questions from the approved design. A person approves anything that creates or changes AWS resources.
          </p>
        </div>
        <a className="btn btn-primary" href="#/new">New design run</a>
      </div>
      {waiting.length > 0 && (
        <div className="card attention" role="region" aria-label="Needs your attention">
          <div className="card-head"><h2>Needs your attention</h2><span className="card-aside">{waiting.length} run{waiting.length === 1 ? "" : "s"} waiting for a person</span></div>
          <ul className="items">
            {waiting.map((r) => (
              <li key={r.runId}><span className="main">{pretty(r.customerId) || r.runId.slice(0, 8)}</span><span className="meta">deploy run <code>{r.runId.slice(0, 8)}</code></span><a className="btn btn-sm btn-primary" href={`#/run/${r.runId}`}>Open</a></li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid-kpi">
        <Kpi label="Runs (30 days)" value={String(s.total)} hint={`${s.delivered} delivered · ${s.failed} failed`} />
        <Kpi label="Success rate" value={s.successRate === null ? "–" : `${s.successRate.toFixed(1)}%`} hint="of finished runs" tone={s.successRate === null ? "" : "green"} />
        <Kpi label="In progress" value={String(s.inProgress)} hint="Running now" tone={s.inProgress ? "amber" : ""} />
        <Kpi label="Failed" value={String(s.failed)} hint="Open a run to see why" tone={s.failed ? "red" : ""} />
      </div>
      <div className="panel panel-pad">
        <div className="card-head"><h2>Recent runs</h2><a className="card-aside" href="#/runs">All runs →</a></div>
        <RunsTable runs={runs.slice(0, 5)} />
      </div>
    </>
  );
}
