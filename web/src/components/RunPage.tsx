import { useCallback, useEffect, useRef, useState } from "react";
import type { ArtifactName, AuditItem, Client, Run } from "../api/client";
import { allActivity, feedText, latestActivity } from "../logic/activity";
import { parseScope } from "../logic/design";
import type { Scope } from "../logic/design";
import { ago, isDone, pretty, stateOf, when } from "../logic/format";
import { pauseNotice } from "../logic/notices";
import { questionKey, isUpdateOnly, answeredPending } from "../logic/question";
import { parseDeploymentReport, parseValidationReport } from "../logic/reports";
import type { DeploymentReport as DeploymentReportData, ValidationReport } from "../logic/reports";
import { deploySteps, designSteps } from "../logic/steps";
import type { Theme } from "../theme";
import { Badge } from "../ui/Badge";
import { CustomScpPanel } from "../ui/CustomScpPanel";
import { DeploymentReport } from "../ui/DeploymentReport";
import { Kpi } from "../ui/Kpi";
import { OrgDiagram } from "../ui/OrgDiagram";
import { ScopePanel } from "../ui/ScopePanel";
import { SecurityPanel } from "../ui/SecurityPanel";
import { useToast } from "../ui/Toasts";
import { AuditFeed } from "./AuditFeed";
import { Progress } from "./Progress";
import { QuestionPanel } from "./QuestionPanel";
import { ResumePanel } from "./ResumePanel";
const msg = (e: unknown): string => (e instanceof Error ? e.message : String(e));
const hasArtifact = (run: Run, k: string): boolean => !!(run.artifacts && (run.artifacts as Record<string, unknown>)[k]);
type TabId = "organization" | "scope" | "scps" | "security" | "deployment" | "activity";
export function RunPage({ runId, api, canAnswer, userSub, pollMs = 4000, onCrumb, onDeploy, theme = "dark" }: {
  runId: string; api: Client; canAnswer: boolean; userSub: string; pollMs?: number; theme?: Theme;
  onCrumb?: (name: string) => void; onDeploy?: (designRunId: string) => void;
}) {
  const toast = useToast();
  const [run, setRun] = useState<Run | null>(null);
  const [audit, setAudit] = useState<AuditItem[]>([]);
  const [scope, setScope] = useState<{ scope: Scope; diagram: string } | null>(null);
  const [scopeError, setScopeError] = useState("");
  const [report, setReport] = useState<ValidationReport | null>(null);
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
    } catch (e) {
      setError(msg(e));
      setStale(true);
    }
  }, [api, runId]);
  useEffect(() => { setRun(null); setScope(null); setReport(null); setDepReport(null); void load(); }, [load]);
  useEffect(() => {
    if (!run || isDone(run.status)) return;
    const t = setInterval(() => void load(), pollMs);
    return () => clearInterval(t);
  }, [run, load, pollMs]);
  const deploy = run?.runKind === "deploy";
  const scopeRunId = run ? (run.designRunId ?? (deploy ? null : run.runId)) : null;
  const designReady = !!run && (isDone(run.status) || audit.some((a) => a.action === "phase.completed"));
  useEffect(() => {
    if (!scopeRunId || !designReady || scope) return;
    api.getScope(scopeRunId)
      .then((d) => { setScope({ scope: parseScope(d.scope), diagram: d.orgDiagram }); setScopeError(""); })
      .catch((e: unknown) => setScopeError(msg(e)));
  }, [api, scopeRunId, designReady, scope]);
  const reportSha = run && hasArtifact(run, "report");
  useEffect(() => {
    if (!run || deploy || !reportSha || report) return;
    api.getReportSummary(run.runId)
      .then((d) => { setReport(parseValidationReport(d.report)); setReportError(""); })
      .catch((e: unknown) => setReportError(msg(e)));
  }, [api, run, deploy, reportSha, report]);
  const depSha = run && hasArtifact(run, "deployment-report");
  useEffect(() => {
    if (!run || !deploy || !depSha || depReport) return;
    api.getArtifact(run.runId, "deployment-report")
      .then((d) => { setDepReport(parseDeploymentReport(d.deploymentReport)); setReportError(""); })
      .catch((e: unknown) => setReportError(msg(e)));
  }, [api, run, deploy, depSha, depReport]);
  const name = scope?.scope.customer.orgName ?? (run ? pretty(run.customerId) || run.runId.slice(0, 8) : "");
  useEffect(() => { if (name) onCrumb?.(`${name} ${deploy ? "deploy" : "design"}`); }, [name, deploy, onCrumb]);
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
  const steps = deploy ? deploySteps(run, audit) : designSteps(run, audit);
  const recent = latestActivity(audit);
  const pause = deploy && !isDone(run.status) ? pauseNotice(audit, run) : null;
  const sc = scope?.scope;
  const tabs: { id: TabId; label: string; count?: number }[] = [];
  if (deploy && depReport) tabs.push({ id: "deployment", label: "Deployment report" });
  if (sc && scope.diagram) tabs.push({ id: "organization", label: "Organization" });
  if (sc) tabs.push({ id: "scope", label: "Scope" });
  if (sc && !deploy) tabs.push({ id: "scps", label: "Custom SCPs", count: sc.customScps.length });
  if (report) tabs.push({ id: "security", label: "Security and validation" });
  tabs.push({ id: "activity", label: "Activity" });
  const current = tabs.find((t) => t.id === tab)?.id ?? tabs[0]!.id;
  const missing = sc?.missingRequired ?? [];
  const questions = sc?.openQuestions.length ?? 0;
  const dl = (k: ArtifactName, text: string, primary = false) => (
    <button type="button" className={`btn ${primary ? "btn-primary" : ""}`} disabled={!(k === "reports" ? hasArtifact(run, k) : delivered && hasArtifact(run, k))} onClick={() => void download(k)}>{text}</button>
  );
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
          <br />{deploy ? "Open the Activity tab to see where it stopped." : "A failed design run can't be resumed. Start a new run, or open the Activity tab to see where it stopped."}
        </div>
      )}
      {typeof run.credentialsCleanupError === "string" && run.credentialsCleanupError && (
        <div className="notice notice-err" role="alert">
          <strong>Stored target credentials were not deleted.</strong> {String(run.credentialsCleanupError)}
          <br /><span className="hint">Ask a platform operator to delete them from the artifact bucket and rotate the access key.</span>
        </div>
      )}
      {error && !stale && <p className="errtext" role="alert">{error}</p>}
      {deploy && run.status === "FAILED" && <ResumePanel run={run} api={api} onResumed={() => void load()} />}
      {pending && (
        <QuestionPanel key={questionKey(pending)} run={run}
          pending={pending} canAnswer={canAnswer} userSub={userSub} api={api} onChanged={() => void load()} />
      )}
      {!pending && pause && (
        <div className={`notice notice-${pause.tone}`} role="status"><strong>{pause.title}</strong> {pause.body}{pause.hint && <><br /><span className="hint">{pause.hint}</span></>}</div>
      )}
      <div className="grid-3">
        <div className="card"><div className="card-head"><h2>Progress</h2></div><Progress steps={steps} /></div>
        {deploy && recent.length > 0 && (
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
        <div className="card">
          <div className="card-head"><h2>Downloads</h2></div>
          <div className="row">
            {deploy ? (<>
              {dl("deployment-report", "Deployment report", true)}{dl("foundation-assessment", "Foundation assessment")}
              {dl("iac-change-plan", "IaC change plan")}{dl("iac-manifest", "IaC manifest")}
            </>) : (<>{dl("terraform", "Terraform", true)}{dl("cloudformation", "CloudFormation")}{dl("reports", "Scan reports")}</>)}
          </div>
          <p className="hint">
            {deploy
              ? delivered ? "Foundation attestation, IaC plan, manifest and evidence from the deploy workflow." : run.status === "FAILED" ? "Deliverables appear here if attestation completed before the failure." : "Available when the deploy run finishes."
              : delivered ? "Each zip includes the docs, the custom SCPs for review, and its own scan reports." : run.status === "FAILED" ? (hasArtifact(run, "reports") ? "The code isn't available because validation failed. The scan reports are." : "The code isn't available because the run failed.") : "Ready when validation finishes."}
          </p>
          {!deploy && delivered && onDeploy && (<>
            <h3>Deploy</h3>
            <p className="hint">Run the deploy agent against a target AWS account. AWS Transform builds the landing zone from this design.</p>
            <button type="button" className="btn btn-primary" onClick={() => onDeploy(run.runId)}>Start deploy run</button>
          </>)}
        </div>
        {!deploy && (missing.length > 0 || questions > 0) && (
          <div className="card">
            <div className="card-head"><h2>Before you apply</h2></div>
            {missing.length > 0 && (<>
              <ul className="todo">{missing.map((n) => <li key={n}><b>!</b><span>{n[0]!.toUpperCase() + n.slice(1)}</span></li>)}</ul>
              <p className="hint">Each account needs a unique root email that has never been used for another AWS account. Terraform reads them from <code>terraform.tfvars</code>, CloudFormation from the parameter files.</p>
            </>)}
            {questions > 0 && <p>{questions} open question{questions === 1 ? "" : "s"} to confirm with the customer. <button type="button" className="btn-link" onClick={() => setTab("scope")}>Review</button></p>}
          </div>
        )}
      </div>
      {sc && !deploy && (
        <div className="grid-kpi">
          <Kpi label="OUs" value={String(sc.summary.ous)} /><Kpi label="Accounts" value={String(sc.summary.accounts)} />
          <Kpi label="Controls enabled" value={String(sc.summary.controlAttachments)} /><Kpi label="Catalog SCPs" value={String(sc.summary.scps)} />
          <Kpi label="Custom SCPs" value={String(sc.summary.customScps ?? 0)} hint="for review" tone={sc.summary.customScps ? "amber" : ""} />
        </div>
      )}
      {!sc && !isDone(run.status) && !deploy && (
        <div className="card"><div className="card-head"><h2><span className="spin" /> The agent is reading the SOW</h2></div>
          <p className="hint">This usually takes a few minutes. You can leave this page: the run continues and stays under Runs.</p></div>
      )}
      {scopeError && (deploy || delivered) && <p className="errtext" role="alert">The approved design could not be shown: {scopeError}</p>}
      {reportError && <p className="errtext" role="alert">A report could not be shown: {reportError}</p>}
      <div className="panel panel-pad">
        <div className="tabs" role="tablist" aria-label="Run details">
          {tabs.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={current === t.id} className="tab" onClick={() => setTab(t.id)}>
              {t.label}{t.count ? <span className="count">{t.count}</span> : null}
            </button>
          ))}
        </div>
        {current === "deployment" && depReport && <DeploymentReport report={depReport} onDownload={() => void download("deployment-report")} />}
        {current === "organization" && scope && <OrgDiagram source={scope.diagram} theme={theme} />}
        {current === "scope" && sc && <ScopePanel scope={sc} />}
        {current === "scps" && sc && <CustomScpPanel scope={sc} />}
        {current === "security" && report && <SecurityPanel report={report} onDownload={(n) => void download(n)} />}
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
