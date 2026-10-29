import { useCallback, useEffect, useState } from "react";
import type { AuditItem, Client, Run, Schemas } from "../api/client";
import { allActivity, feedText, latestActivity } from "../logic/activity";
import { ago, isDone, pretty, stateOf, when } from "../logic/format";
import { deploySteps } from "../logic/steps";
import { AuditFeed } from "./AuditFeed";
import { DesignPanel } from "./DesignPanel";
import { QuestionPanel } from "./QuestionPanel";
import { Badge } from "./RunsTable";
import { ResumePanel } from "./ResumePanel";

type Tab = "activity" | "design" | "details";

export function RunPage({ runId, api, canAnswer, userSub, pollMs = 4000, onCrumb }: {
  runId: string; api: Client; canAnswer: boolean; userSub: string; pollMs?: number; onCrumb?: (name: string) => void;
}) {
  const [run, setRun] = useState<Run | null>(null);
  const [audit, setAudit] = useState<AuditItem[]>([]);
  const [design, setDesign] = useState<Schemas["ScopeData"] | null>(null);
  const [tab, setTab] = useState<Tab>("activity");
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const [all, setAll] = useState(false);

  const load = useCallback(async () => {
    try {
      const [r, a] = await Promise.all([api.getRun(runId), api.getAudit(runId)]);
      setRun(r.run);
      setAudit(a.audit);
      setError("");
      setStale(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStale(true);
    }
  }, [api, runId]);

  useEffect(() => { setRun(null); setDesign(null); void load(); }, [load]);
  useEffect(() => {
    if (!run || isDone(run.status)) return;
    const t = setInterval(() => void load(), pollMs);
    return () => clearInterval(t);
  }, [run, load, pollMs]);

  const scopeRunId = run?.designRunId ?? (run && !run.runKind ? run.runId : null);
  useEffect(() => {
    if (!scopeRunId) return;
    api.getScope(scopeRunId).then(setDesign).catch(() => setDesign(null));
  }, [api, scopeRunId]);

  const name = run ? pretty(run.customerId) || run.runId.slice(0, 8) : "";
  useEffect(() => { if (name) onCrumb?.(`${name} ${run?.runKind === "deploy" ? "deploy" : "design"}`); }, [name, run?.runKind, onCrumb]);

  async function stop() {
    try {
      await api.stopRun(runId);
      setConfirmStop(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!run) return <p className="empty">{error || "Loading…"}</p>;
  const deploy = run.runKind === "deploy";
  const [tone, label] = stateOf(run.status);
  const pending = run.status === "RUNNING" ? run.pendingHumanInput : undefined;
  const steps = deploy ? deploySteps(run, audit) : [];
  const recent = latestActivity(audit);

  return (
    <div className="run">
      <div className="crumbs"><a href="#/runs">← Runs</a></div>
      <h1 className="page-title">
        {name} <Badge tone={deploy ? "violet" : "muted"}>{deploy ? "Deploy" : "Design"}</Badge> <Badge tone={tone}>{label}</Badge>
        {!isDone(run.status) && (
          <span className={`live${stale ? " stale" : ""}`} role="status"><i aria-hidden="true" />{stale ? "Reconnecting…" : "Live"}</span>
        )}
        {run.status === "RUNNING" && deploy && (
          confirmStop ? (
            <span role="group" aria-label="Confirm stop" className="confirm">
              <span className="hint">Stop this run? It is marked failed and can be resumed later.</span>
              <button type="button" className="btn btn-sm" onClick={stop}>Yes, stop it</button>
              <button type="button" className="btn btn-sm" onClick={() => setConfirmStop(false)}>Cancel</button>
            </span>
          ) : (
            <button type="button" className="btn btn-sm" onClick={() => setConfirmStop(true)}>Stop run</button>
          )
        )}
      </h1>
      <p className="page-sub">
        {run.createdAt ? `Started ${when(run.createdAt)} · ` : ""}{deploy ? "Deploy" : "Design"} run <code>{run.runId.slice(0, 8)}</code>
        {run.designRunId && <> · Design run <a href={`#/run/${run.designRunId}`}><code>{run.designRunId.slice(0, 8)}</code></a></>}
      </p>

      {run.status === "FAILED" && (
        <div className="notice notice-err" role="alert">
          <strong>{deploy ? "Deploy failed." : "This run failed."}</strong> {run.error || "No reason was recorded."}
          <br />Open the Activity tab to see where it stopped.
        </div>
      )}
      {error && !stale && <p className="errtext" role="alert">{error}</p>}
      {deploy && run.status === "FAILED" && <ResumePanel run={run} api={api} onResumed={() => void load()} />}
      {pending && (
        <QuestionPanel key={`${pending.jobId}:${pending.messageId ?? pending.taskId ?? pending.title}`} run={run}
          pending={pending} canAnswer={canAnswer} userSub={userSub} api={api} onChanged={() => void load()} />
      )}

      {deploy && (
        <div className="grid-3">
          <div className="card">
            <div className="card-head"><h2>Progress</h2></div>
            <div className="steps">
              {steps.map((s) => (
                <div key={s.name} className={`step ${s.state}${s.waiting ? " waiting" : ""}`}>
                  <div className="step-rail"><span className="step-node" /><span className="step-line" /></div>
                  <div className="step-body"><div className="step-name">{s.name}</div><div className="step-sub">{s.sub}</div></div>
                  <span className="step-check">{s.state === "done" ? "✓" : s.state === "failed" ? "✕" : ""}</span>
                </div>
              ))}
            </div>
          </div>
          {recent.length > 0 && (
            <div className="card">
              <div className="card-head"><h2>Latest activity</h2><button type="button" className="btn-link" onClick={() => setTab("activity")}>All events</button></div>
              <ol className="feed" aria-live="polite">
                {recent.map((a) => (
                  <li key={a.SK} className={/failed/.test(a.action) ? "bad" : ""}>
                    <time dateTime={new Date(a.ts * 1000).toISOString()} title={new Date(a.ts * 1000).toLocaleString()}>{ago(a.ts)}</time>
                    <span>{feedText(a, userSub)}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}

      <div className="panel panel-pad">
        <div className="tabs" role="tablist" aria-label="Run details">
          {(["activity", "design", "details"] as Tab[]).map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} className="tab" onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>
        {tab === "activity" && (<>
          <label className="check"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show every step</label>
          <AuditFeed audit={allActivity(audit, all)} userSub={userSub} />
        </>)}
        {tab === "design" && (design ? <DesignPanel scope={design.scope} diagram={design.orgDiagram} /> : <p className="hint">No approved design to show yet.</p>)}
        {tab === "details" && (
          <dl className="kv">
            <dt>Run</dt><dd><code>{run.runId}</code></dd>
            {run.designRunId && (<><dt>Design run</dt><dd><code>{run.designRunId}</code></dd></>)}
            {run.targetRegion && (<><dt>Control Tower Region</dt><dd>{run.targetRegion}</dd></>)}
            {run.accountEmailBase && (<><dt>Account email</dt><dd>{run.accountEmailBase}</dd></>)}
            {run.mapAgreement && (<><dt>MAP agreement</dt><dd>{run.mapAgreement}</dd></>)}
            {run.resumeCount ? (<><dt>Resumed</dt><dd>{run.resumeCount} time{run.resumeCount === 1 ? "" : "s"}</dd></>) : null}
            {run.deployTarget && (<><dt>Deploy target</dt><dd><code>{JSON.stringify(run.deployTarget)}</code></dd></>)}
          </dl>
        )}
      </div>
    </div>
  );
}
