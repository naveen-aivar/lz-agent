import { useCallback, useEffect, useState } from "react";
import type { AuditItem, Client, Run, Schemas } from "../api/client";
import { AuditFeed } from "./AuditFeed";
import { DesignPanel } from "./DesignPanel";
import { QuestionPanel } from "./QuestionPanel";

type Tab = "activity" | "design" | "details";
const DONE = new Set(["DELIVERED", "FAILED"]);

export function RunPage({ runId, api, canAnswer, userSub, pollMs = 4000 }: {
  runId: string; api: Client; canAnswer: boolean; userSub: string; pollMs?: number;
}) {
  const [run, setRun] = useState<Run | null>(null);
  const [audit, setAudit] = useState<AuditItem[]>([]);
  const [design, setDesign] = useState<Schemas["ScopeData"] | null>(null);
  const [tab, setTab] = useState<Tab>("activity");
  const [error, setError] = useState("");
  const [confirmStop, setConfirmStop] = useState(false);
  const [all, setAll] = useState(false);

  const load = useCallback(async () => {
    try {
      const [r, a] = await Promise.all([api.getRun(runId), api.getAudit(runId)]);
      setRun(r.run);
      setAudit(a.audit);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [api, runId]);

  useEffect(() => { setRun(null); setDesign(null); void load(); }, [load]);
  useEffect(() => {
    if (!run || DONE.has(run.status)) return;
    const t = setInterval(() => void load(), pollMs);
    return () => clearInterval(t);
  }, [run, load, pollMs]);

  const scopeRunId = run?.designRunId ?? (run && !run.runKind ? run.runId : null);
  useEffect(() => {
    if (!scopeRunId) return;
    api.getScope(scopeRunId).then(setDesign).catch(() => setDesign(null));
  }, [api, scopeRunId]);

  async function stop() {
    try {
      await api.stopRun(runId);
      setConfirmStop(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!run) return <p>{error || "Loading…"}</p>;
  const pending = run.status === "RUNNING" ? run.pendingHumanInput : undefined;

  return (
    <div className="run">
      <h1>{run.customerId ?? run.runId.slice(0, 8)} <span className={`badge badge-${run.status.toLowerCase()}`}>{run.status}</span></h1>
      {run.error && <p className="error" role="alert">{run.error}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {run.status === "RUNNING" && run.runKind === "deploy" && (
        confirmStop ? (
          <p role="group" aria-label="Confirm stop">Stop this run? The workflow aborts and the run is marked failed.{" "}
            <button type="button" className="btn btn-sm" onClick={stop}>Yes, stop it</button>{" "}
            <button type="button" className="btn btn-sm" onClick={() => setConfirmStop(false)}>Cancel</button></p>
        ) : (
          <button type="button" className="btn btn-sm" onClick={() => setConfirmStop(true)}>Stop run</button>
        )
      )}
      {pending && (
        <QuestionPanel key={`${pending.jobId}:${pending.messageId ?? pending.taskId ?? pending.title}`} run={run}
          pending={pending} canAnswer={canAnswer} userSub={userSub} api={api} onChanged={() => void load()} />
      )}
      <nav role="tablist">
        {(["activity", "design", "details"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className="tab" onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>
      {tab === "activity" && (<>
        <label className="hint"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show every step</label>
        <AuditFeed audit={audit} all={all} />
      </>)}
      {tab === "design" && (design ? <DesignPanel scope={design.scope} diagram={design.orgDiagram} /> : <p className="hint">No approved design to show yet.</p>)}
      {tab === "details" && (
        <dl>
          <dt>Run</dt><dd><code>{run.runId}</code></dd>
          {run.designRunId && (<><dt>Design run</dt><dd><code>{run.designRunId}</code></dd></>)}
          {run.targetRegion && (<><dt>Control Tower Region</dt><dd>{run.targetRegion}</dd></>)}
          {run.accountEmailBase && (<><dt>Account email</dt><dd>{run.accountEmailBase}</dd></>)}
          {run.mapAgreement && (<><dt>MAP agreement</dt><dd>{run.mapAgreement}</dd></>)}
          {run.deployTarget && (<><dt>Deploy target</dt><dd><code>{JSON.stringify(run.deployTarget)}</code></dd></>)}
        </dl>
      )}
    </div>
  );
}
