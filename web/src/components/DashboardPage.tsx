import type { Client } from "../api/client";
import { runStats } from "../logic/stats";
import { RunsTable } from "./RunsTable";
import { useRuns } from "./useRuns";

const Kpi = ({ label, value, hint, tone = "" }: { label: string; value: string; hint: string; tone?: string }) => (
  <div className={`kpi ${tone ? "kpi-" + tone : ""}`}>
    <div className="kpi-label">{label}</div><div className="kpi-value">{value}</div><div className="kpi-hint">{hint}</div>
  </div>
);

export function DashboardPage({ api }: { api: Client }) {
  const { runs, error } = useRuns(api);
  if (error) return <p className="errtext" role="alert">{error}</p>;
  if (!runs) return <p className="empty">Loading…</p>;
  const s = runStats(runs);
  return (
    <>
      <h1 className="page-title">Landing Zone</h1>
      <p className="page-sub">
        Turn a customer's statement of work into landing zone code, then deploy it with AWS Transform. The deploy agent answers
        Transform's questions from the approved design; a person approves anything that creates or changes AWS resources.
      </p>
      <div className="grid-kpi">
        <Kpi label="Runs (30 days)" value={String(s.total)} hint={`${s.delivered} delivered · ${s.failed} failed`} />
        <Kpi label="Success rate" value={s.successRate === null ? "–" : `${s.successRate.toFixed(1)}%`} hint="of finished runs" tone={s.successRate === null ? "" : "green"} />
        <Kpi label="In progress" value={String(s.inProgress)} hint="Running now" tone={s.inProgress ? "amber" : ""} />
        <Kpi label="Failed" value={String(s.failed)} hint="Open a run to see why" tone={s.failed ? "red" : ""} />
      </div>
      <div className="card">
        <div className="card-head"><h2>Start a run</h2></div>
        <p className="hint">New design runs (upload a SOW) are still started in the classic UI. Deploy a delivered design from the run history below.</p>
        <p><a className="btn btn-primary btn-sm" href="/">Open the classic UI</a></p>
      </div>
      <div className="panel panel-pad">
        <div className="card-head"><h2>Recent runs</h2><a className="card-aside" href="#/runs">All runs →</a></div>
        <RunsTable runs={runs.slice(0, 5)} />
      </div>
    </>
  );
}
