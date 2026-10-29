import { useCallback, useEffect, useRef, useState } from "react";
import type { ArtifactName, AuditItem, Client, Run } from "../api/client";
import { allActivity, feedText, latestActivity } from "../logic/activity";
import { parseScope } from "../logic/design";
import type { Scope } from "../logic/design";
import { ago, isDone, pretty, stateOf, when } from "../logic/format";
import { pauseNotice } from "../logic/notices";
import { answeredPending, isUpdateOnly, questionKey } from "../logic/question";
import { parseDeploymentReport } from "../logic/reports";
import type { DeploymentReport as DeploymentReportData } from "../logic/reports";
import { deploySteps } from "../logic/steps";
import type { Theme } from "../theme";
import { Badge } from "../ui/Badge";
import { DeploymentReport } from "../ui/DeploymentReport";
import { OrgDiagram } from "../ui/OrgDiagram";
import { ScopePanel } from "../ui/ScopePanel";
import { useToast } from "../ui/Toasts";
import { AuditFeed } from "./AuditFeed";
import { Progress } from "./Progress";
import { QuestionPanel } from "./QuestionPanel";
import { ResumePanel } from "./ResumePanel";
const msg = (e: unknown): string => (e instanceof Error ? e.message : String(e));
const hasArtifact = (run: Run, k: string): boolean => !!(run.artifacts && (run.artifacts as Record<string, unknown>)[k]);
type TabId = "organization" | "scope" | "deployment" | "activity";
/** A deploy run: what AWS Transform is asking, progress, and the results. Inside a project (`embedded`) the design is on its own step. */
export function RunPage({ runId, api, canAnswer, userSub, pollMs = 4000, onCrumb, onLoaded, theme = "dark", embedded = false, view = "progress" }: {
  runId: string; api: Client; canAnswer: boolean; userSub: string; pollMs?: number; theme?: Theme; embedded?: boolean;
  /** "results" shows only the finished run's report and downloads. */
  view?: "progress" | "results";
  onCrumb?: (name: string) => void; onLoaded?: (run: Run) => void;
}) {
  const toast = useToast();
  const [run, setRun] = useState<Run | null>(null);
  const [audit, setAudit] = useState<AuditItem[]>([]);
  const [scope, setScope] = useState<{ scope: Scope; diagram: string } | null>(null);
  const [scopeError, setScopeError] = useState("");
  const [depReport, setDepReport] = useState<DeploymentReportData | null>(null);
  const [reportError, setReportError] = useState("");
  const [tab, setTab] = useState<TabId | null>(null);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const [all, setAll] = useState(false);
  const seenQuestion = useRef<string | null>(null);
  const load = useCallback(async () => {
    try {
      const [r, a] = await Promise.all([api.getRun(runId), api.getAudit(runId)]);
      setRun(r.run);
      setAudit(a.audit);
      setError("");
      setStale(false);
      onLoaded?.(r.run);
    } catch (e) {
      setError(msg(e));
      setStale(true);
    }
  }, [api, runId, onLoaded]);
  useEffect(() => { setRun(null); setScope(null); setDepReport(null); void load(); }, [load]);
  useEffect(() => {
    if (!run || isDone(run.status)) return;
    const t = setInterval(() => void load(), pollMs);
    return () => clearInterval(t);
  }, [run, load, pollMs]);
  const designId = run?.designRunId;
  useEffect(() => {
    if (embedded || !designId || scope) return;
    api.getScope(designId)
      .then((d) => { setScope({ scope: parseScope(d.scope), diagram: d.orgDiagram }); setScopeError(""); })
      .catch((e: unknown) => setScopeError(msg(e)));
  }, [api, designId, embedded, scope]);
  const depSha = run && hasArtifact(run, "deployment-report");
  useEffect(() => {
    if (!run || !depSha || depReport) return;
    api.getArtifact(run.runId, "deployment-report")
      .then((d) => { setDepReport(parseDeploymentReport(d.deploymentReport)); setReportError(""); })
      .catch((e: unknown) => setReportError(msg(e)));
  }, [api, run, depSha, depReport]);
  const name = scope?.scope.customer.orgName ?? (run ? pretty(run.customerId) || run.runId.slice(0, 8) : "");
  useEffect(() => { if (name && !embedded) onCrumb?.(`${name} deploy`); }, [name, embedded, onCrumb]);
  const pending = run?.status === "RUNNING" ? run.pendingHumanInput : undefined;
  const needsInput = !!run && !!pending && !isUpdateOnly(pending) && !answeredPending(run, pending);
  useEffect(() => {
    const key = needsInput && pending ? questionKey(pending) : null;
    if (seenQuestion.current === null) { seenQuestion.current = key ?? ""; }
    else if (key && key !== seenQuestion.current) { seenQuestion.current = key; toast("AWS Transform needs your input"); }
    const base = document.title.replace(/^● Input needed · /, "");
    document.title = needsInput ? `● Input needed · ${base}` : base;
    return () => { document.title = base; };
  }, [needsInput, pending, toast]);
  async function stop() {
    try {
      await api.stopRun(runId);
      setConfirmStop(false);
      await load();
    } catch (e) {
      setError(msg(e));
    }
  }
  async function download(artifact: ArtifactName) {
    try {
      const { url, filename } = await api.getArtifact(runId, artifact);
      if (!url) throw new Error("the API returned no download link");
      const a = Object.assign(document.createElement("a"), { href: url, download: filename ?? "" });
      document.body.appendChild(a); a.click(); a.remove();
      toast("Download started");
    } catch (e) {
      toast(msg(e), "bad");
    }
  }
  if (!run) return <p className="empty">{error || "Loading…"}</p>;
  const [tone, label] = stateOf(run.status);
  const delivered = run.status === "DELIVERED";
  const steps = deploySteps(run, audit);
  const recent = latestActivity(audit);
  const pause = !isDone(run.status) ? pauseNotice(audit, run) : null;
  const sc = scope?.scope;
  const tabs: { id: TabId; label: string }[] = [];
  if (depReport) tabs.push({ id: "deployment", label: "Deployment report" });
  if (sc && scope.diagram) tabs.push({ id: "organization", label: "Organization" });
  if (sc) tabs.push({ id: "scope", label: "Scope" });
  tabs.push({ id: "activity", label: "Activity" });
  const current = tabs.find((t) => t.id === tab)?.id ?? tabs[0]!.id;
  const dl = (k: ArtifactName, text: string, primary = false) => (
    <button type="button" className={`btn ${primary ? "btn-primary" : ""}`} disabled={!(delivered && hasArtifact(run, k))} onClick={() => void download(k)}>{text}</button>
  );
  const downloads = (
    <div className="card">
      <div className="card-head"><h2>Downloads</h2></div>
      <div className="row">{dl("deployment-report", "Deployment report", true)}{dl("foundation-assessment", "Foundation assessment")}{dl("iac-change-plan", "IaC change plan")}{dl("iac-manifest", "IaC manifest")}</div>
      <p className="hint">
        {delivered ? "Foundation attestation, IaC plan, manifest and evidence from the deploy workflow." : run.status === "FAILED" ? "Deliverables appear here if attestation completed before the failure." : "Available when the deploy finishes."}
      </p>
    </div>
  );
  if (view === "results") {
    return (
      <div className="run">
        {depReport ? <div className="card"><DeploymentReport report={depReport} onDownload={() => void download("deployment-report")} /></div> : <p className="hint">{reportError || "The deployment report is not available."}</p>}
        {downloads}
      </div>
    );
  }
  return (
    <div className="run">
      {!embedded && <div className="crumbs"><a href="#/runs">← Projects</a></div>}
      <h1 className={embedded ? "sub-title" : "page-title"}>
        {embedded ? "Deploy run" : name} {!embedded && <Badge tone="violet">Deploy</Badge>} <Badge tone={tone}>{label}</Badge>
        {!isDone(run.status) && (
          <span className={`live${stale ? " stale" : ""}`} role="status"><i aria-hidden="true" />{stale ? "Reconnecting…" : "Live"}</span>
        )}
        {run.status === "RUNNING" && (
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
        {run.createdAt ? `Started ${when(run.createdAt)} · ` : ""}Deploy run <code>{run.runId.slice(0, 8)}</code>
        {run.designRunId && !embedded && <> · Design run <a href={`#/run/${run.designRunId}`}><code>{run.designRunId.slice(0, 8)}</code></a></>}
      </p>
      {run.status === "FAILED" && (
        <div className="notice notice-err" role="alert">
          <strong>Deploy stopped.</strong> {run.error || "No reason was recorded."}
          <br />Open the Activity tab to see where it stopped.
        </div>
      )}
      {typeof run.credentialsCleanupError === "string" && run.credentialsCleanupError && (
        <div className="notice notice-err" role="alert">
          <strong>Stored target credentials were not deleted.</strong> {String(run.credentialsCleanupError)}
          <br /><span className="hint">Ask a platform operator to delete them from the artifact bucket and rotate the access key.</span>
        </div>
      )}
      {error && !stale && <p className="errtext" role="alert">{error}</p>}
      {run.status === "FAILED" && <ResumePanel run={run} api={api} onResumed={() => void load()} />}
      {pending && (
        <QuestionPanel key={questionKey(pending)} run={run}
          pending={pending} canAnswer={canAnswer} userSub={userSub} api={api} onChanged={() => void load()} />
      )}
      {!pending && pause && (
        <div className={`notice notice-${pause.tone}`} role="status"><strong>{pause.title}</strong> {pause.body}{pause.hint && <><br /><span className="hint">{pause.hint}</span></>}</div>
      )}
      <div className="grid-3">
        <div className="card"><div className="card-head"><h2>Progress</h2></div><Progress steps={steps} /></div>
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
        {downloads}
      </div>
      {scopeError && <p className="errtext" role="alert">The approved design could not be shown: {scopeError}</p>}
      {reportError && <p className="errtext" role="alert">A report could not be shown: {reportError}</p>}
      <div className="panel panel-pad">
        <div className="tabs" role="tablist" aria-label="Run details">
          {tabs.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={current === t.id} className="tab" onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>
        {current === "deployment" && depReport && <DeploymentReport report={depReport} onDownload={() => void download("deployment-report")} />}
        {current === "organization" && scope && <OrgDiagram source={scope.diagram} theme={theme} />}
        {current === "scope" && sc && <ScopePanel scope={sc} />}
        {current === "activity" && (<>
          <label className="check"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show every step</label>
          <AuditFeed audit={allActivity(audit, all)} userSub={userSub} />
          <dl className="kv" style={{ marginTop: 16 }}>
            <dt>Run</dt><dd><code>{run.runId}</code></dd>
            {run.targetRegion && (<><dt>Control Tower Region</dt><dd>{run.targetRegion}</dd></>)}
            {run.accountEmailBase && (<><dt>Account email</dt><dd>{run.accountEmailBase}</dd></>)}
            {run.mapAgreement && (<><dt>MAP agreement</dt><dd>{run.mapAgreement}</dd></>)}
            {run.resumeCount ? (<><dt>Resumed</dt><dd>{run.resumeCount} time{run.resumeCount === 1 ? "" : "s"}</dd></>) : null}
            {run.deployTarget && (<><dt>Deploy target</dt><dd><code>{JSON.stringify({ ...run.deployTarget, secretAccessKey: undefined, sessionToken: undefined })}</code></dd></>)}
          </dl>
        </>)}
      </div>
    </div>
  );
}
